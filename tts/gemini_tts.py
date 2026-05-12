#!/usr/bin/env python3
"""Gemini TTS integration for video pipeline.

Uses Google's Gemini 2.5 Flash/Pro TTS models which are deeply multimodal,
allowing rich voice profiles and context-aware speech generation.
"""
import asyncio
import base64
import json
import os
import shutil
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types

from shared.replicate_client import is_mock_mode, is_tts_test_mode

# Mock fixtures
MOCK_AUDIO_FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "mock_audio.mp3"


def _estimate_mock_tts_cost_usd(text: str) -> float:
    """Small deterministic mock cost for cost-plumbing tests."""
    # Roughly $0.001 per 1k chars, with a small minimum.
    chars = max(0, len(text or ""))
    return max(0.01, round((chars / 1000.0) * 0.001, 4))


def _jsonable(value: Any) -> Any:
    """Best-effort conversion to something json.dumps can serialize."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}

    # Pydantic / dataclasses / protobuf-ish objects
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return _jsonable(fn())
            except Exception:
                pass

    # Protobuf message
    if hasattr(value, "DESCRIPTOR"):
        try:
            from google.protobuf.json_format import MessageToDict  # type: ignore
            return _jsonable(MessageToDict(value, preserving_proto_field_name=True))
        except Exception:
            pass

    try:
        return _jsonable(vars(value))
    except Exception:
        return str(value)


# Available Gemini TTS voices (30 prebuilt voices for 3.1 Flash TTS)
GEMINI_VOICES = [
    # Female voices
    "Achernar", "Aoede", "Autonoe", "Callirrhoe", "Despina", "Erinome",
    "Gacrux", "Kore", "Laomedeia", "Leda", "Pulcherrima", "Sulafat",
    "Vindemiatrix", "Zephyr",
    # Male voices
    "Achird", "Algenib", "Algieba", "Alnilam", "Charon", "Enceladus",
    "Fenrir", "Iapetus", "Orus", "Puck", "Rasalgethi", "Sadachbia",
    "Sadaltager", "Schedar", "Umbriel", "Zubenelgenubi",
]

# Default voice settings
DEFAULT_VOICE = "Kore"
DEFAULT_MODEL = "gemini-3.1-flash-tts-preview"
SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2
CHANNELS = 1



def _pcm_to_wav(pcm_data: bytes, output_path: Path) -> None:
    """Convert raw PCM data to WAV file."""
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)


def _wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    """Convert WAV to MP3 using ffmpeg."""
    import subprocess
    cmd = [
        "ffmpeg", "-y",
        "-i", str(wav_path),
        "-codec:a", "libmp3lame",
        "-b:a", "192k",
        str(mp3_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr}")


class GeminiTTS:
    """Gemini TTS client for speech synthesis."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
    ):
        """Initialize Gemini TTS client.

        Args:
            model: Gemini TTS model to use
            api_key: Google API key (defaults to GOOGLE_API_KEY env var)
        """
        self.model = model
        self.last_usage_metadata: Optional[Dict[str, Any]] = None
        api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable must be set")
        self.client = genai.Client(api_key=api_key)

    def synthesize(
        self,
        text: str,
        voice_name: str = DEFAULT_VOICE,
        voice_prompt: Optional[str] = None,
        script_context: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Synthesize speech from text.

        Args:
            text: Text to synthesize
            voice_name: Gemini voice name (e.g., "Kore", "Puck")
            voice_prompt: Optional style/direction prompt for the voice
            script_context: Optional full script context for better synthesis

        Returns:
            Raw PCM audio data (24kHz, 16-bit, mono)
        """
        # Build the content with context
        content_parts = []

        # Add voice prompt/direction if provided
        if voice_prompt:
            content_parts.append(f"[Voice Direction]\n{voice_prompt}\n\n")

        # Add script context if provided (helps model understand the full narrative)
        if script_context:
            title = script_context.get("script_title", "")
            subject = script_context.get("subject", "")
            if title or subject:
                content_parts.append(f"[Context: {title} - {subject}]\n\n")

        # Add the actual text to speak
        content_parts.append(f"[Speak the following text]\n{text}")

        full_content = "".join(content_parts)

        # Generate speech
        response = self.client.models.generate_content(
            model=self.model,
            contents=full_content,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice_name,
                        )
                    )
                ),
            ),
        )
        # Capture usage metadata if provided
        try:
            usage_meta = getattr(response, "usage_metadata", None)
            self.last_usage_metadata = _jsonable(usage_meta) if usage_meta else None
        except Exception:
            self.last_usage_metadata = None

        # Extract audio data
        audio_data = b""
        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                audio_data += part.inline_data.data

        return audio_data

    def synthesize_to_file(
        self,
        text: str,
        output_path: Path,
        voice_name: str = DEFAULT_VOICE,
        voice_prompt: Optional[str] = None,
        script_context: Optional[Dict[str, Any]] = None,
        output_format: str = "mp3",
    ) -> Path:
        """Synthesize speech and save to file.

        Args:
            text: Text to synthesize
            output_path: Output file path
            voice_name: Gemini voice name
            voice_prompt: Optional voice direction prompt
            script_context: Optional script context
            output_format: Output format ("wav" or "mp3")

        Returns:
            Path to output file
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Mock mode: copy mock audio file instead of calling API
        if is_mock_mode() and not is_tts_test_mode():
            print(f"[MOCK] Skipping Gemini TTS API call, using mock audio")
            if MOCK_AUDIO_FIXTURE.exists():
                shutil.copy(MOCK_AUDIO_FIXTURE, output_path)
                self.last_usage_metadata = {
                    "estimated_cost": _estimate_mock_tts_cost_usd(text),
                    "mock": True,
                    "model": self.model,
                }
                return output_path
            else:
                raise FileNotFoundError(f"Mock audio fixture not found: {MOCK_AUDIO_FIXTURE}")

        pcm_data = self.synthesize(
            text=text,
            voice_name=voice_name,
            voice_prompt=voice_prompt,
            script_context=script_context,
        )

        if output_format == "wav":
            _pcm_to_wav(pcm_data, output_path)
        elif output_format == "mp3":
            # Write to temp WAV first, then convert
            wav_path = output_path.with_suffix(".wav")
            _pcm_to_wav(pcm_data, wav_path)
            _wav_to_mp3(wav_path, output_path)
            wav_path.unlink()  # Clean up temp file
        else:
            raise ValueError(f"Unsupported output format: {output_format}")

        return output_path


class BatchGeminiTTS:
    """Batch Gemini TTS for processing multiple scenes."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        concurrency: int = 3,
    ):
        """Initialize batch TTS client.

        Args:
            model: Gemini TTS model
            api_key: Google API key
            concurrency: Max concurrent requests
        """
        self.model = model
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        self.concurrency = concurrency
        self._semaphore: Optional[asyncio.Semaphore] = None

    def _get_client(self) -> GeminiTTS:
        """Create a new TTS client instance."""
        return GeminiTTS(model=self.model, api_key=self.api_key)

    async def _synthesize_one(
        self,
        text: str,
        output_path: Path,
        voice_name: str,
        voice_prompt: Optional[str],
        script_context: Optional[Dict[str, Any]],
        output_format: str,
    ) -> Tuple[Path, Dict[str, Any]]:
        """Synthesize one item with semaphore control."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency)

        async with self._semaphore:
            # Run sync synthesis in thread pool
            loop = asyncio.get_event_loop()
            client = self._get_client()

            result_path = await loop.run_in_executor(
                None,
                lambda: client.synthesize_to_file(
                    text=text,
                    output_path=output_path,
                    voice_name=voice_name,
                    voice_prompt=voice_prompt,
                    script_context=script_context,
                    output_format=output_format,
                )
            )

            # Create metadata (timestamps not available from Gemini TTS)
            metadata = {
                "text": text,
                "voice_name": voice_name,
                "model": self.model,
                "has_voice_prompt": voice_prompt is not None,
            }
            usage_meta = getattr(client, "last_usage_metadata", None)
            if usage_meta is not None:
                metadata["usage"] = usage_meta

            return result_path, metadata

    async def synthesize_batch(
        self,
        requests: List[Dict[str, Any]],
        output_dir: Path,
        script_context: Optional[Dict[str, Any]] = None,
        output_format: str = "mp3",
    ) -> List[Tuple[Path, Dict[str, Any]]]:
        """Synthesize multiple texts concurrently.

        Args:
            requests: List of dicts with "text", "filename", optional "voice_name"
            output_dir: Output directory
            script_context: Optional script context
            output_format: Output format

        Returns:
            List of (output_path, metadata) tuples
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        tasks = []
        for req in requests:
            text = req.get("text", "")
            if not text.strip():
                continue

            filename = req.get("filename", "output")
            if not filename.endswith(f".{output_format}"):
                filename = f"{Path(filename).stem}.{output_format}"

            output_path = output_dir / filename

            voice_name = req.get("voice_name") or DEFAULT_VOICE

            tasks.append(
                self._synthesize_one(
                    text=text,
                    output_path=output_path,
                    voice_name=voice_name,
                    voice_prompt=None,
                    script_context=script_context,
                    output_format=output_format,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and log them
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[ERROR] TTS synthesis failed for request {i}: {result}")
            else:
                final_results.append(result)

        return final_results


def synthesize_narration(
    script_data: Dict[str, Any],
    output_dir: Path,
    voice_name: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    concurrency: int = 3,
    output_format: str = "mp3",
) -> List[Tuple[Path, Path]]:
    """Synthesize narration for all scenes in a script.

    Args:
        script_data: Script data with scenes
        output_dir: Output directory for audio files
        voice_name: Voice name to use (defaults to DEFAULT_VOICE)
        model: Gemini TTS model
        concurrency: Concurrent requests
        output_format: Output format

    Returns:
        List of (audio_path, metadata_path) tuples
    """
    output_dir = Path(output_dir)

    # Build requests from scenes
    requests = []
    for scene in script_data.get("scenes", []):
        text = (scene.get("narrator") or "").strip()
        scene_number = scene.get("scene_number", 0)
        filename = f"scene{int(scene_number):02d}.{output_format}"
        requests.append({
            "text": text,
            "filename": filename,
            "voice_name": voice_name,
        })

    # Run batch synthesis
    client = BatchGeminiTTS(model=model, concurrency=concurrency)

    async def _run():
        return await client.synthesize_batch(
            requests=requests,
            output_dir=output_dir,
            script_context=script_data,
            output_format=output_format,
        )

    results = asyncio.run(_run())

    # Write metadata files alongside audio
    output_tuples = []
    for audio_path, metadata in results:
        metadata_path = audio_path.with_suffix(".timestamps.json")
        metadata_path.write_text(json.dumps(metadata, indent=2))
        output_tuples.append((audio_path, metadata_path))
        print(f"[ok] {audio_path.name}")

    return output_tuples


# CLI for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gemini TTS synthesis")
    parser.add_argument("text", nargs="?", help="Text to synthesize")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help=f"Voice name (default: {DEFAULT_VOICE})")
    parser.add_argument("--out", "-o", type=Path, default=Path("output.mp3"), help="Output file")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini TTS model")
    parser.add_argument("--list-voices", action="store_true", help="List available voices")

    args = parser.parse_args()

    if args.list_voices:
        print("Available Gemini TTS voices:")
        for voice in GEMINI_VOICES:
            print(f"  - {voice}")
        exit(0)

    if not args.text:
        parser.error("text is required for synthesis")

    # Synthesize
    client = GeminiTTS(model=args.model)

    print(f"Synthesizing with voice '{args.voice}'...")
    output = client.synthesize_to_file(
        text=args.text,
        output_path=args.out,
        voice_name=args.voice,
    )
    print(f"Saved to {output}")
