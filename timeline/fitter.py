"""Fit adjustment module — applies speed/extend/trim to media files."""

import asyncio
from pathlib import Path

from shared.media import (
    change_audio_speed,
    change_video_speed_async,
    concat_audio,
    extend_video_async,
    generate_silence,
    run_cmd,
    trim_video_async,
)

DURATION_TOLERANCE = 0.05
MIN_SPEED_FACTOR = 0.25
MAX_SPEED_FACTOR = 4.0
VALID_METHODS = {"speed", "extend", "trim"}


async def apply_fit(
    clip_path: Path,
    method: str,
    raw_duration: float,
    target_duration: float,
    media_type: str,
    run_dir: Path,
    clip_id: str,
) -> Path:
    """Apply a fit method to adjust media to the target duration.

    Returns the path to the adjusted media file, or the original path
    if no adjustment is needed (durations already match within tolerance).
    """
    if method not in VALID_METHODS:
        raise ValueError(f"Invalid fit method '{method}'. Must be one of: {VALID_METHODS}")

    if not clip_path.exists():
        raise FileNotFoundError(f"Media file not found: {clip_path}")

    if abs(raw_duration - target_duration) < DURATION_TOLERANCE:
        return clip_path

    if method == "speed":
        return await _apply_speed(clip_path, raw_duration, target_duration, media_type, run_dir, clip_id)
    elif method == "extend":
        return await _apply_extend(clip_path, raw_duration, target_duration, media_type, run_dir, clip_id)
    else:  # trim
        return await _apply_trim(clip_path, raw_duration, target_duration, media_type, run_dir, clip_id)


def apply_fit_sync(
    clip_path: Path,
    method: str,
    raw_duration: float,
    target_duration: float,
    media_type: str,
    run_dir: Path,
    clip_id: str,
) -> Path:
    """Synchronous wrapper for apply_fit."""
    return asyncio.run(apply_fit(clip_path, method, raw_duration, target_duration, media_type, run_dir, clip_id))


def _dest_path(media_type: str, run_dir: Path, clip_id: str) -> Path:
    if media_type == "video":
        dest = run_dir / "videos_adjusted" / f"{clip_id}.mp4"
    else:
        dest = run_dir / "audio" / f"{clip_id}_fitted.wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


async def _apply_speed(
    clip_path: Path, raw_duration: float, target_duration: float,
    media_type: str, run_dir: Path, clip_id: str,
) -> Path:
    if target_duration <= 0:
        # Almost always a resumed node whose NodeResult carries no duration.
        # Left as a bare ZeroDivisionError this reads as a generic warning and
        # the run continues, shipping a video with its narration cut off.
        raise ValueError(
            f"Cannot fit to a target duration of {target_duration}. The fit "
            f"target has no measured duration — usually a resumed clip whose "
            f"NodeResult was loaded without probing the file. "
            f"raw_duration={raw_duration}"
        )
    speed_factor = raw_duration / target_duration
    if speed_factor < MIN_SPEED_FACTOR or speed_factor > MAX_SPEED_FACTOR:
        raise ValueError(
            f"Speed factor {speed_factor:.2f} is outside allowed range "
            f"[{MIN_SPEED_FACTOR}, {MAX_SPEED_FACTOR}]. "
            f"raw_duration={raw_duration}, target_duration={target_duration}"
        )

    dest = _dest_path(media_type, run_dir, clip_id)

    if media_type == "video":
        await change_video_speed_async(clip_path, speed_factor, dest)
    else:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: change_audio_speed(clip_path, speed_factor, dest, preserve_pitch=True)
        )

    return dest


async def _apply_extend(
    clip_path: Path, raw_duration: float, target_duration: float,
    media_type: str, run_dir: Path, clip_id: str,
) -> Path:
    dest = _dest_path(media_type, run_dir, clip_id)

    if raw_duration < target_duration:
        extra = target_duration - raw_duration
        if media_type == "video":
            await extend_video_async(clip_path, extra, dest)
        else:
            silence_path = run_dir / "audio" / f"{clip_id}_silence.wav"
            silence_path.parent.mkdir(parents=True, exist_ok=True)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: generate_silence(extra, silence_path))
            await loop.run_in_executor(
                None, lambda: concat_audio([clip_path, silence_path], dest, reencode=True)
            )
    else:
        # raw > target — trim
        if media_type == "video":
            await trim_video_async(clip_path, target_duration, dest)
        else:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: run_cmd([
                    "ffmpeg", "-y", "-i", str(clip_path),
                    "-t", str(target_duration), "-c", "copy", str(dest),
                ]),
            )

    return dest


async def _apply_trim(
    clip_path: Path, raw_duration: float, target_duration: float,
    media_type: str, run_dir: Path, clip_id: str,
) -> Path:
    if raw_duration <= target_duration:
        return clip_path

    dest = _dest_path(media_type, run_dir, clip_id)

    if media_type == "video":
        await trim_video_async(clip_path, target_duration, dest)
    else:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: run_cmd([
                "ffmpeg", "-y", "-i", str(clip_path),
                "-t", str(target_duration), "-c", "copy", str(dest),
            ]),
        )

    return dest
