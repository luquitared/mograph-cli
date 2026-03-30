#!/usr/bin/env python3
import os
import sys
import json
import base64
import argparse
import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from elevenlabs.client import AsyncElevenLabs  # pip install elevenlabs

from shared.common import ensure_dir
from shared.replicate_client import is_mock_mode, is_tts_test_mode

# Mock fixtures
MOCK_AUDIO_FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "mock_audio.mp3"

# --------------------------- Defaults & Voice Map ---------------------------

DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"  # safe + widely supported
DEFAULT_VOICE_SETTINGS = {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.0,
    "use_speaker_boost": True,
}
# ElevenLabs voice name → voice_id mapping (fetched 2025-12-04)
VOICE_NAME_TO_ID = {
    # Male voices
    "Adam":    "pNInz6obpgDQGcFmaJgB",  # male, middle_aged, american - social_media
    "Bill":    "pqHfZKP75CvOlQylNhV4",  # male, old, american - advertisement
    "Brian":   "nPczCjzI2devNBz1zQrb",  # male, middle_aged, american - social_media
    "Callum":  "N2lVS1w4EtoT3dr4eOWO",  # male, middle_aged, american - characters_animation
    "Charlie": "IKne3meq5aSn9XLyUdCD",  # male, young, australian - conversational
    "Chris":   "iP95p4xoKVk53GoZ742B",  # male, middle_aged, american - conversational
    "Daniel":  "onwK4e9ZLuTAKqWW03F9",  # male, middle_aged, british - informative_educational
    "Eric":    "cjVigY5qzO86Huf0OWal",  # male, middle_aged, american - conversational
    "George":  "JBFqnCBsd6RMkjVDRZzb",  # male, middle_aged, british - narrative_story
    "Harry":   "SOYHLrjzK2X1ezoPC6cr",  # male, young, american - characters_animation
    "Liam":    "TX3LPaxmHKxFdv7VOQHJ",  # male, young, american - social_media
    "Roger":   "CwhRBWXzGAHq8TQ4Fs17",  # male, middle_aged, american - conversational
    "Will":    "bIHbv24MWmeRgasZH58o",  # male, young, american - conversational
    # Female voices
    "Alice":   "Xb7hH8MSUJpSbSDYk0k2",  # female, middle_aged, british - advertisement
    "Jessica": "cgSgspJ2msm6clMCkdW9",  # female, young, american - conversational
    "Laura":   "FGY2WhTYpPnrIDTdsKH5",  # female, young, american - social_media
    "Lily":    "pFZP5JQG7iQjIQuC4Bku",  # female, middle_aged, british - informative_educational
    "Matilda": "XrExE9yKIg1WjnnlVkGX",  # female, middle_aged, american - informative_educational
    "Sarah":   "EXAVITQu4vr4xnSDxMaL",  # female, young, american - entertainment_tv
    # Neutral voices
    "River":   "SAz9YHcvj6GT2YYXdXww",  # neutral, middle_aged, american - conversational
}

# ------------------------------ Data Shapes --------------------------------

@dataclass
class RetryPolicy:
    max_attempts: int = 3
    initial_delay: float = 1.0  # seconds
    backoff_factor: float = 2.0
    jitter: float = 0.25  # add up to +/- jitter seconds

# -------------------------------- Utils ------------------------------------

def b64_to_bytes(s: str) -> bytes:
    return base64.b64decode(s)

def resolve_voice_id(req: Dict[str, Any]) -> str:
    # Priority: explicit voice_id -> name lookup -> default mapping fallback
    if vid := req.get("voice_id"):
        return vid
    if vname := req.get("voice"):
        if vname in VOICE_NAME_TO_ID:
            return VOICE_NAME_TO_ID[vname]
    # Fallback to a known voice if nothing supplied
    return VOICE_NAME_TO_ID.get("Sarah", "EXAVITQu4vr4xnSDxMaL")

def merge_params(defaults: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(defaults or {})
    for k, v in (override or {}).items():
        if k == "voice_settings" and v is not None:
            merged_vs = dict(out.get("voice_settings") or {})
            merged_vs.update(v)
            out["voice_settings"] = merged_vs
        else:
            out[k] = v
    return out

async def async_run(cmd: List[str]) -> Tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode("utf-8", "ignore"), stderr.decode("utf-8", "ignore")

async def ffmpeg_concat(input_files: List[Path], output_path: Path, reencode: bool = True) -> None:
    """
    Concatenate audio files in order. We default to re-encoding to avoid
    container/codec mismatch edge cases across clips.
    """
    ensure_dir(output_path.parent)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in input_files:
            # ffmpeg concat demuxer expects escaped paths wrapped in single quotes
            f.write(f"file '{p.as_posix()}'\n")
        list_file = f.name

    if reencode:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", list_file,
            "-c:a", "libmp3lame", "-b:a", "128k",
            output_path.as_posix(),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", list_file,
            "-c", "copy",
            output_path.as_posix(),
        ]

    code, out, err = await async_run(cmd)
    if code != 0:
        raise RuntimeError(f"ffmpeg concat failed ({code}): {err.strip()}")

# ------------------------------- Core Logic --------------------------------

class BatchTTS:
    def __init__(self, api_key: Optional[str], concurrency: int, retry: RetryPolicy):
        self.client = AsyncElevenLabs(api_key=api_key)  # uses env ELEVENLABS_API_KEY if None
        self.sem = asyncio.Semaphore(concurrency)
        self.retry = retry

    async def convert_with_timestamps_once(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calls ElevenLabs 'convert_with_timestamps' endpoint and returns JSON with:
          - audio_base64
          - alignment
          - normalized_alignment
        """
        # Mock mode: return mock audio with fake timestamps
        if is_mock_mode() and not is_tts_test_mode():
            print("[MOCK] Skipping ElevenLabs API call, using mock audio")
            if MOCK_AUDIO_FIXTURE.exists():
                audio_bytes = MOCK_AUDIO_FIXTURE.read_bytes()
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                text = params.get("text", "Mock narration text.")
                # Create mock alignment with evenly spaced characters
                duration = 6.0  # Mock audio is 6 seconds
                chars = list(text)
                char_duration = duration / len(chars) if chars else 0.1
                return {
                    "audio_base64": audio_b64,
                    "alignment": {
                        "characters": chars,
                        "character_start_times_seconds": [i * char_duration for i in range(len(chars))],
                        "character_end_times_seconds": [(i + 1) * char_duration for i in range(len(chars))],
                    },
                    "normalized_alignment": {
                        "characters": chars,
                        "character_start_times_seconds": [i * char_duration for i in range(len(chars))],
                        "character_end_times_seconds": [(i + 1) * char_duration for i in range(len(chars))],
                    },
                }
            else:
                raise FileNotFoundError(f"Mock audio fixture not found: {MOCK_AUDIO_FIXTURE}")

        # Required: voice_id + text. Optional: model_id, output_format, voice_settings, etc.
        return await self.client.text_to_speech.convert_with_timestamps(**params)

    async def backoff_call(self, fn, *args, **kwargs):
        attempt = 0
        delay = self.retry.initial_delay
        while True:
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                attempt += 1
                if attempt >= self.retry.max_attempts:
                    raise
                # jittered exponential backoff
                jitter = (2 * self.retry.jitter * (os.urandom(1)[0] / 255.0) - self.retry.jitter)
                await asyncio.sleep(max(0.05, delay + jitter))
                delay *= self.retry.backoff_factor

    async def synth_one(self, req: Dict[str, Any], defaults: Dict[str, Any], out_dir: Path) -> Tuple[Path, Path]:
        """
        Returns (audio_path, timestamps_path)
        """
        async with self.sem:
            merged = merge_params(defaults, req)
            voice_id = resolve_voice_id(merged)
            text = merged.get("text")
            if not text:
                raise ValueError("Every request must include 'text'.")
            model_id = merged.get("model_id", DEFAULT_MODEL)
            output_format = merged.get("output_format", DEFAULT_OUTPUT_FORMAT)
            voice_settings = merged.get("voice_settings", DEFAULT_VOICE_SETTINGS)
            seed = merged.get("seed", None)
            language_code = merged.get("language_code", None)

            # Filename / paths
            filename = merged.get("filename") or "output.mp3"
            # Try to infer extension from output_format
            ext = (output_format.split("_", 1)[0] if "_" in output_format else "mp3").replace("pcm","wav")
            if not filename.lower().endswith(f".{ext}"):
                filename = f"{Path(filename).stem}.{ext}"
            audio_path = out_dir / filename
            timestamps_path = out_dir / f"{Path(filename).stem}.timestamps.json"

            # Build call params
            call_params = {
                "voice_id": voice_id,
                "text": text,
                "model_id": model_id,
                "output_format": output_format,
                "voice_settings": voice_settings,
            }
            if seed is not None:
                call_params["seed"] = seed
            if language_code is not None:
                call_params["language_code"] = language_code

            # Optional continuity helpers if present:
            for k in ("previous_text", "next_text", "previous_request_ids", "next_request_ids",
                      "apply_text_normalization", "apply_language_text_normalization"):
                if k in merged:
                    call_params[k] = merged[k]

            # Do the call (with retries)
            resp = await self.backoff_call(self.convert_with_timestamps_once, call_params)

            # The response has audio_base_64 (with underscores) as an attribute
            audio_bytes = b64_to_bytes(resp.audio_base_64)
            
            ensure_dir(audio_path.parent)
            audio_path.write_bytes(audio_bytes)

            # Persist sidecar timestamps
            # Convert pydantic models to dicts for JSON serialization
            alignment = None
            normalized_alignment = None
            
            if hasattr(resp, 'alignment') and resp.alignment:
                alignment = resp.alignment.model_dump() if hasattr(resp.alignment, 'model_dump') else resp.alignment
            
            if hasattr(resp, 'normalized_alignment') and resp.normalized_alignment:
                normalized_alignment = resp.normalized_alignment.model_dump() if hasattr(resp.normalized_alignment, 'model_dump') else resp.normalized_alignment
            
            sidecar = {
                "text": text,
                "model_id": model_id,
                "voice_id": voice_id,
                "output_format": output_format,
                "voice_settings": voice_settings,
                "alignment": alignment,
                "normalized_alignment": normalized_alignment,
            }
            timestamps_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2))

            return audio_path, timestamps_path


# ----------------------------- Forced Alignment -----------------------------

async def forced_alignment(
    audio_path: Path,
    transcript: str,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Use ElevenLabs Forced Alignment API to get word-level timestamps
    for an audio file and its transcript.

    Args:
        audio_path: Path to audio file (mp3, wav, etc.)
        transcript: Text transcript of the audio
        api_key: ElevenLabs API key (uses env if None)

    Returns:
        Dict with 'characters', 'words', and 'loss' from the alignment
    """
    # Mock mode: return mock alignment data
    if is_mock_mode() and not is_tts_test_mode():
        print("[MOCK] Skipping ElevenLabs forced alignment API, using mock timestamps")
        words = transcript.split()
        duration = 6.0  # Mock audio is 6 seconds
        word_duration = duration / len(words) if words else 0.5
        mock_words = []
        for i, word in enumerate(words):
            mock_words.append({
                "text": word,
                "start": i * word_duration,
                "end": (i + 1) * word_duration,
            })
        chars = list(transcript)
        char_duration = duration / len(chars) if chars else 0.1
        mock_chars = []
        for i, char in enumerate(chars):
            mock_chars.append({
                "text": char,
                "start": i * char_duration,
                "end": (i + 1) * char_duration,
            })
        return {
            "characters": mock_chars,
            "words": mock_words,
            "loss": 0.0,
        }

    client = AsyncElevenLabs(api_key=api_key or os.getenv("ELEVENLABS_API_KEY"))

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    result = await client.forced_alignment.create(
        file=audio_bytes,
        text=transcript,
    )

    # Convert to dict
    if hasattr(result, "model_dump"):
        return result.model_dump()
    elif hasattr(result, "__dict__"):
        return {
            "characters": [c.model_dump() if hasattr(c, "model_dump") else c for c in (result.characters or [])],
            "words": [w.model_dump() if hasattr(w, "model_dump") else w for w in (result.words or [])],
            "loss": result.loss,
        }
    return result


def forced_alignment_sync(
    audio_path: Path,
    transcript: str,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Synchronous wrapper for forced_alignment."""
    return asyncio.run(forced_alignment(audio_path, transcript, api_key))


def get_word_timestamps(alignment_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract word-level timestamps from forced alignment result.

    Args:
        alignment_result: Result from forced_alignment()

    Returns:
        List of dicts with 'word', 'start', 'end' for each word
    """
    words = alignment_result.get("words", [])
    return [
        {
            "word": w.get("text", ""),
            "start": w.get("start", 0),
            "end": w.get("end", 0),
        }
        for w in words
    ]


# --------------------------------- CLI -------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Async ElevenLabs batch TTS with timestamps + optional concat.")
    p.add_argument("jobs_json", type=Path, help="Path to jobs JSON file.")
    p.add_argument("--out", type=Path, default=Path("tts_out"), help="Output directory for individual clips.")
    p.add_argument("--combine", action="store_true", help="If set, concatenate all generated audio clips.")
    p.add_argument("--combine-out", type=Path, default=Path("tts_out/combined/output.mp3"),
                   help="Where to write the concatenated audio if --combine is set.")
    p.add_argument("--concurrency", type=int, default=4, help="Max concurrent API requests.")
    p.add_argument("--max-attempts", type=int, default=3, help="Max retry attempts per request.")
    p.add_argument("--initial-delay", type=float, default=1.0, help="Initial backoff delay in seconds.")
    p.add_argument("--backoff-factor", type=float, default=2.0, help="Backoff multiplier.")
    p.add_argument("--jitter", type=float, default=0.25, help="Jitter range (+/- seconds) added to delay.")
    return p

async def main_async(args: argparse.Namespace) -> None:
    # Load jobs file
    jobs = json.loads(Path(args.jobs_json).read_text())

    defaults = jobs.get("defaults", {})
    # Fill sensible defaults if not provided
    defaults.setdefault("model_id", DEFAULT_MODEL)
    defaults.setdefault("output_format", DEFAULT_OUTPUT_FORMAT)
    defaults.setdefault("voice_settings", DEFAULT_VOICE_SETTINGS)

    requests_list = jobs.get("requests", [])
    if not isinstance(requests_list, list) or not requests_list:
        raise SystemExit("jobs_json must include a non-empty 'requests' array")

    # Allow JSON to override concurrency/retries as well
    concurrency = int(jobs.get("concurrency", args.concurrency))
    retry_policy = RetryPolicy(
        max_attempts=int(jobs.get("retries", {}).get("max_attempts", args.max_attempts)),
        initial_delay=float(jobs.get("retries", {}).get("initial_delay", args.initial_delay)),
        backoff_factor=float(jobs.get("retries", {}).get("backoff_factor", args.backoff_factor)),
        jitter=float(jobs.get("retries", {}).get("jitter", args.jitter)),
    )

    client = BatchTTS(api_key=os.getenv("ELEVENLABS_API_KEY"), concurrency=concurrency, retry=retry_policy)

    out_dir = args.out
    ensure_dir(out_dir)

    tasks = []
    for req in requests_list:
        tasks.append(client.synth_one(req, defaults, out_dir))

    # Run with concurrency + collect results
    results: List[Tuple[Path, Path]] = []
    try:
        for coro in asyncio.as_completed(tasks):
            audio_path, ts_path = await coro
            results.append((audio_path, ts_path))
            print(f"[ok] {audio_path.name}  (timestamps: {ts_path.name})")
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        raise

    # Combine if requested (CLI flag) or JSON config combine_audio.enabled == true
    combine_cfg = jobs.get("combine_audio", {})
    combine_enabled = args.combine or bool(combine_cfg.get("enabled", False))
    if combine_enabled and results:
        # Sort to preserve JSON order (results already reflect completion order).
        # We'll re-read intended order from the original requests array.
        stem_to_path = {p.name: p for p, _ in results}
        ordered_files: List[Path] = []
        for req in requests_list:
            # Derive the actual emitted filename again to ensure match:
            desired_ext = (req.get("output_format") or defaults.get("output_format", DEFAULT_OUTPUT_FORMAT))
            ext = (desired_ext.split("_", 1)[0] if "_" in desired_ext else "mp3").replace("pcm","wav")
            fname = req.get("filename") or "output.mp3"
            if not fname.lower().endswith(f".{ext}"):
                fname = f"{Path(fname).stem}.{ext}"
            p = out_dir / fname
            if p.exists():
                ordered_files.append(p)
            else:
                # fallback to known results if user supplied odd name
                if p.name in stem_to_path:
                    ordered_files.append(stem_to_path[p.name])

        combine_out = args.combine_out
        # Allow JSON override
        if "output_path" in combine_cfg:
            combine_out = Path(combine_cfg["output_path"])

        await ffmpeg_concat(ordered_files, combine_out, reencode=True)
        print(f"[combined] Wrote: {combine_out.as_posix()}")

def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)

if __name__ == "__main__":
    main()
