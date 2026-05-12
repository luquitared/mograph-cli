"""TTS generation adapter for timeline sources.

Translates timeline TTSSource objects into calls to the existing
GeminiTTS.synthesize_to_file() API, with concurrency control and
optional forced alignment for word-level timestamps.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.replicate_client import is_mock_mode, set_mock_mode
from timeline.model import NodeResult, Project, TTSDefaults, TTSSource

logger = logging.getLogger(__name__)

# Timeline canonical names → actual model IDs used by GeminiTTS
TTS_MODEL_MAP: Dict[str, str] = {
    "gemini-3.1-flash-tts": "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-tts": "gemini-2.5-flash-preview-tts",
}


def _resolve_model(name: str) -> str:
    """Map a timeline model name to the actual Gemini model ID."""
    return TTS_MODEL_MAP.get(name, name)


def _build_script_context(project: Optional[Project]) -> Optional[Dict[str, Any]]:
    """Derive script_context dict from project metadata."""
    if not project:
        return None
    ctx: Dict[str, Any] = {}
    if project.name:
        ctx["title"] = project.name
    if project.description:
        ctx["description"] = project.description
    return ctx or None


def _resolve_voice(source: TTSSource, defaults: TTSDefaults) -> str:
    """Pick voice from source, falling back to defaults."""
    return source.voice or defaults.voice or "Kore"


def _resolve_voice_prompt(
    source: TTSSource, defaults: TTSDefaults
) -> Optional[str]:
    """Pick voice_prompt from source, falling back to defaults."""
    return source.voice_prompt if source.voice_prompt is not None else defaults.voice_prompt


async def _try_forced_alignment(
    path: Path,
    text: str,
    clip_id: str,
    audio_dir: Path,
) -> None:
    """Attempt forced alignment and save timestamps JSON. Non-fatal."""
    loop = asyncio.get_running_loop()
    try:
        from tts.eleven import forced_alignment_sync

        alignment = await loop.run_in_executor(
            None, forced_alignment_sync, path, text
        )
        ts_path = audio_dir / f"{clip_id}.timestamps.json"
        ts_path.write_text(json.dumps(alignment, indent=2))
        logger.debug("Saved timestamps for %s → %s", clip_id, ts_path)
    except Exception as exc:  # noqa: BLE001
        # Missing ELEVENLABS_API_KEY, network error, etc. — skip gracefully
        logger.debug("Forced alignment skipped for %s: %s", clip_id, exc)


async def generate_tts(
    sources: List[Tuple[str, TTSSource]],
    run_dir: Path,
    defaults: TTSDefaults,
    project: Optional[Project] = None,
    concurrency: int = 3,
) -> Dict[str, NodeResult]:
    """Generate TTS audio from TTSSource objects.

    Args:
        sources: List of (clip_id, TTSSource) pairs.
        run_dir: Run directory; audio written to ``run_dir/audio/``.
        defaults: Fallback TTS settings.
        project: Optional project metadata for script_context.
        concurrency: Max parallel synthesis calls.

    Returns:
        Mapping of clip_id → NodeResult(path, duration, media_type="audio").
        Clips that fail are logged and omitted.
    """
    if not sources:
        return {}

    from tts.gemini_tts import GeminiTTS
    from shared.media import probe_duration_async

    # Resolve default model; per-clip model may override below
    current_model = _resolve_model(defaults.model)
    client = GeminiTTS(model=current_model)
    script_context = _build_script_context(project)

    audio_dir = run_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    results: Dict[str, NodeResult] = {}

    async def process_one(clip_id: str, source: TTSSource) -> None:
        nonlocal current_model, client
        async with sem:
            output_path = audio_dir / f"{clip_id}.mp3"
            voice = _resolve_voice(source, defaults)
            voice_prompt = _resolve_voice_prompt(source, defaults)

            # Per-clip model override (MAJOR-6)
            clip_model = _resolve_model(source.model) if source.model else current_model
            if clip_model != current_model:
                current_model = clip_model
                client = GeminiTTS(model=current_model)

            # Save generation inputs before API call
            inputs_dir = run_dir / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            input_record = {
                "type": "tts",
                "model": clip_model,
                "clip_id": clip_id,
                "text": source.text,
                "voice": voice,
                "voice_prompt": voice_prompt,
                "script_context": script_context,
            }
            (inputs_dir / f"{clip_id}.json").write_text(json.dumps(input_record, indent=2))

            try:
                loop = asyncio.get_running_loop()
                # Capture mock_mode from the caller thread so it can be
                # propagated into the executor thread (thread-local storage).
                _mock = is_mock_mode()
                # Capture client ref for closure
                _client = client

                def _synth() -> Path:
                    if _mock:
                        set_mock_mode(True)
                    try:
                        return _client.synthesize_to_file(
                            text=source.text,
                            output_path=output_path,
                            voice_name=voice,
                            voice_prompt=voice_prompt,
                            script_context=script_context,
                        )
                    finally:
                        if _mock:
                            set_mock_mode(False)

                path = await loop.run_in_executor(None, _synth)
                duration = await probe_duration_async(path)
                results[clip_id] = NodeResult(
                    path=path, duration=duration, media_type="audio"
                )
                logger.info(
                    "TTS generated: %s (%.2fs)", clip_id, duration
                )

                # Attempt forced alignment (non-fatal)
                await _try_forced_alignment(path, source.text, clip_id, audio_dir)

            except Exception as exc:  # noqa: BLE001
                logger.error("TTS failed for %s: %s", clip_id, exc)

    tasks = [process_one(cid, src) for cid, src in sources]
    await asyncio.gather(*tasks)

    return results
