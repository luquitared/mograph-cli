#!/usr/bin/env python3
"""
Media processing utilities using FFmpeg.

Consolidated FFmpeg operations for video/audio processing.
This module replaces ffmpeg_utils.py and centralizes all media operations.
"""
import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from PIL import Image


# Common encoding settings
H264_SETTINGS = [
    "-c:v", "libx264",
    "-preset", "fast",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-threads", "2",
]

AAC_SETTINGS = [
    "-c:a", "aac",
    "-ar", "48000",
    "-ac", "2",
    "-b:a", "192k",
]


def run_cmd(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command, optionally raising RuntimeError on failure.

    Args:
        cmd: Command and arguments
        check: If True, raise on non-zero exit code

    Returns:
        CompletedProcess instance

    Raises:
        RuntimeError: If check=True and command fails
    """
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result


def probe_duration(path: Path) -> float:
    """Get duration of a media file in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path.as_posix(),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"Unable to parse duration from ffprobe output: {result.stdout}") from exc


def get_audio_duration(audio_path: Path) -> float:
    """Get duration of an audio file in seconds. Alias for probe_duration."""
    return probe_duration(audio_path)


def change_audio_speed(
    audio_path: Path,
    speed_factor: float,
    dest: Path,
    preserve_pitch: bool = True,
) -> None:
    """Change audio playback speed without (optionally) changing pitch.

    Uses ffmpeg's atempo filter which preserves pitch. The atempo filter
    only accepts values between 0.5 and 2.0, so for larger changes we
    chain multiple filters.

    Args:
        audio_path: Source audio file
        speed_factor: Speed multiplier (>1 speeds up, <1 slows down)
        dest: Output path
        preserve_pitch: If True, use atempo (pitch preserved). If False, use
                       asetrate (pitch changes with speed).
    """
    if speed_factor <= 0:
        raise ValueError("speed_factor must be > 0")

    dest.parent.mkdir(parents=True, exist_ok=True)

    if preserve_pitch:
        # atempo filter only accepts 0.5-2.0, so we chain filters for larger changes
        filters = []
        remaining = speed_factor

        if remaining > 1.0:
            while remaining > 2.0:
                filters.append("atempo=2.0")
                remaining /= 2.0
            if remaining > 1.0:
                filters.append(f"atempo={remaining:.6f}")
        else:
            while remaining < 0.5:
                filters.append("atempo=0.5")
                remaining /= 0.5
            if remaining < 1.0:
                filters.append(f"atempo={remaining:.6f}")

        if not filters:
            filters = ["atempo=1.0"]

        filter_str = ",".join(filters)
        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path.as_posix(),
            "-af", filter_str,
            "-c:a", "libmp3lame",
            "-q:a", "2",
            dest.as_posix(),
        ]
    else:
        sample_rate = 44100
        new_rate = int(sample_rate * speed_factor)
        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path.as_posix(),
            "-af", f"asetrate={new_rate},aresample={sample_rate}",
            "-c:a", "libmp3lame",
            "-q:a", "2",
            dest.as_posix(),
        ]

    run_cmd(cmd)


def detect_aspect_ratio(image_path: Path) -> Tuple[Optional[float], Optional[str]]:
    """Detect aspect ratio from an image file.

    Args:
        image_path: Path to image file

    Returns:
        Tuple of (ratio_float, ratio_string) where ratio_string is "16:9" or "9:16"
        Returns (None, None) if detection fails
    """
    try:
        with Image.open(image_path) as img:
            if img.height == 0:
                return None, None
            ratio = img.width / img.height
            if abs(ratio - 16/9) < 0.1:
                return ratio, "16:9"
            elif abs(ratio - 9/16) < 0.1:
                return ratio, "9:16"
            return ratio, None
    except Exception:
        return None, None


def trim_video(video_path: Path, duration: float, dest: Path) -> None:
    """Trim video to specified duration using stream copy (fast)."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path.as_posix(),
        "-t", f"{duration:.6f}",
        "-c", "copy",
        dest.as_posix(),
    ]
    run_cmd(cmd)


def extend_video(video_path: Path, extra_seconds: float, dest: Path) -> None:
    """Extend video by freezing the last frame for extra_seconds."""
    filter_str = f"[0:v]tpad=stop_mode=clone:stop_duration={extra_seconds:.6f},setpts=PTS-STARTPTS[v]"
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path.as_posix(),
        "-filter_complex", filter_str,
        "-map", "[v]",
        "-an",
        *H264_SETTINGS,
        dest.as_posix(),
    ]
    run_cmd(cmd)


def change_video_speed(video_path: Path, speed_multiplier: float, dest: Path) -> None:
    """Change playback speed for a video (video-only). speed_multiplier > 1 speeds up."""
    if speed_multiplier <= 0:
        raise ValueError("speed_multiplier must be > 0")
    filter_str = f"setpts=PTS/{speed_multiplier:.6f}"
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path.as_posix(),
        "-an",
        "-filter:v", filter_str,
        *H264_SETTINGS,
        dest.as_posix(),
    ]
    run_cmd(cmd)


def overlay_audio(
    video_path: Path,
    audio_path: Path,
    dest: Path,
    pad_audio_to_video: bool = False,
) -> None:
    """Overlay audio onto video.

    Args:
        video_path: Path to video file
        audio_path: Path to audio file
        dest: Output path
        pad_audio_to_video: If True, pad audio with silence to match video duration
    """
    if pad_audio_to_video:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path.as_posix(),
            "-i", audio_path.as_posix(),
            "-filter_complex", "[1:a]apad[a]",
            "-map", "0:v:0",
            "-map", "[a]",
            "-c:v", "copy",
            *AAC_SETTINGS,
            "-movflags", "+faststart",
            "-shortest",
            dest.as_posix(),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path.as_posix(),
            "-i", audio_path.as_posix(),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            *AAC_SETTINGS,
            "-movflags", "+faststart",
            "-shortest",
            dest.as_posix(),
        ]
    run_cmd(cmd)


def combine_audio_tracks(
    video_path: Path,
    narration_path: Path,
    dest: Path,
    narration_volume: float = 1.0,
    video_audio_volume: float = 0.3,
    pad_narration: bool = True,
) -> None:
    """Combine video's original audio (model-generated SFX) with narration overlay.

    Args:
        video_path: Path to video file (with generated audio)
        narration_path: Path to ElevenLabs narration audio
        dest: Output path for combined audio file
        narration_volume: Volume multiplier for narration (default: 1.0 = full volume)
        video_audio_volume: Volume multiplier for video audio (default: 0.3 = 30%)
        pad_narration: If True, pad narration with silence to match video duration
    """
    if pad_narration:
        filter_complex = (
            f"[0:a]volume={video_audio_volume}[vaud];"
            f"[1:a]apad,volume={narration_volume}[narr];"
            f"[vaud][narr]amix=inputs=2:duration=first:dropout_transition=0[out]"
        )
    else:
        filter_complex = (
            f"[0:a]volume={video_audio_volume}[vaud];"
            f"[1:a]volume={narration_volume}[narr];"
            f"[vaud][narr]amix=inputs=2:duration=longest:dropout_transition=0[out]"
        )

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path.as_posix(),
        "-i", narration_path.as_posix(),
        "-filter_complex", filter_complex,
        "-map", "0:v:0",
        "-map", "[out]",
        "-c:v", "copy",
        *AAC_SETTINGS,
        "-movflags", "+faststart",
        dest.as_posix(),
    ]
    run_cmd(cmd)


def overlay_combined_audio(
    video_path: Path,
    narration_path: Path,
    dest: Path,
    sfx_audio_source: Optional[Path] = None,
    narration_volume: float = 1.0,
    video_audio_volume: float = 0.3,
    pad_narration: bool = True,
) -> None:
    """Overlay video with combined audio (model-generated SFX + narration).

    Args:
        video_path: Path to video file (used for video stream)
        narration_path: Path to ElevenLabs narration audio
        dest: Output video path
        sfx_audio_source: Path to audio source to use as SFX (if different from video_path)
        narration_volume: Volume multiplier for narration (default: 1.0 = full volume)
        video_audio_volume: Volume multiplier for SFX audio (default: 0.3 = 30%)
        pad_narration: If True, pad narration with silence to match video duration
    """
    audio_source = sfx_audio_source if sfx_audio_source else video_path

    if sfx_audio_source:
        # Three inputs: video, sfx audio source, narration
        filter_complex = (
            f"[1:a]apad,volume={video_audio_volume}[vaud];"
            f"[2:a]apad,volume={narration_volume}[narr];"
            f"[vaud][narr]amix=inputs=2:duration=longest:dropout_transition=0[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path.as_posix(),
            "-i", audio_source.as_posix(),
            "-i", narration_path.as_posix(),
            "-filter_complex", filter_complex,
            "-map", "0:v:0",
            "-map", "[out]",
            "-c:v", "copy",
            *AAC_SETTINGS,
            "-movflags", "+faststart",
            "-shortest",
            dest.as_posix(),
        ]
    else:
        # Two inputs: video (with audio), narration
        filter_complex = (
            f"[0:a]apad,volume={video_audio_volume}[vaud];"
            f"[1:a]apad,volume={narration_volume}[narr];"
            f"[vaud][narr]amix=inputs=2:duration=longest:dropout_transition=0[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path.as_posix(),
            "-i", narration_path.as_posix(),
            "-filter_complex", filter_complex,
            "-map", "0:v:0",
            "-map", "[out]",
            "-c:v", "copy",
            *AAC_SETTINGS,
            "-movflags", "+faststart",
            "-shortest",
            dest.as_posix(),
        ]
    run_cmd(cmd)


def concat_videos(paths: Iterable[Path], dest: Path, *, reencode: bool = False) -> None:
    """Concatenate multiple videos into one.

    Args:
        paths: Iterable of video file paths
        dest: Output path
        reencode: If True, re-encode (slower but more compatible). If False, try stream copy first.
    """
    paths = list(paths)
    if not paths:
        raise ValueError("No videos provided to concatenate")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as list_file:
        for p in paths:
            p = Path(p)
            abs_path = p if p.is_absolute() else p.resolve()
            if not abs_path.exists():
                raise FileNotFoundError(f"Video not found for concatenation: {abs_path}")
            list_file.write(f"file '{abs_path.as_posix()}'\n")
        concat_list = list_file.name

    try:
        if reencode:
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                *H264_SETTINGS,
                *AAC_SETTINGS,
                "-movflags", "+faststart",
                dest.as_posix(),
            ]
            run_cmd(cmd)
        else:
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                dest.as_posix(),
            ]
            try:
                run_cmd(cmd)
            except RuntimeError:
                # Fallback to re-encode if stream copy fails
                concat_videos(paths, dest, reencode=True)
    finally:
        Path(concat_list).unlink(missing_ok=True)


def generate_silence(duration: float, dest: Path) -> None:
    """Generate a silent audio file of specified duration."""
    safe_duration = max(duration, 0.1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", f"{safe_duration:.6f}",
        dest.as_posix(),
    ]
    run_cmd(cmd)


def extract_last_frame(video_path: Path, dest: Path) -> Path:
    """Extract the last frame from a video file as a PNG image."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-sseof", "-0.1",  # Seek to 0.1 seconds before end
        "-i", video_path.as_posix(),
        "-vframes", "1",
        "-q:v", "2",  # High quality
        dest.as_posix(),
    ]
    run_cmd(cmd)
    if not dest.exists():
        raise RuntimeError(f"Failed to extract last frame from {video_path}")
    return dest


def extract_first_frame(video_path: Path, dest: Path) -> Path:
    """Extract first frame from video as image."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-frames:v", "1", str(dest)
    ], capture_output=True, check=True)
    return dest


def extract_audio_track(video_path: Path, dest: Path) -> Path:
    """Extract audio track from video file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "copy", str(dest)
    ], capture_output=True, check=True)
    return dest


def image_to_video(image_path: Path, duration: float, dest: Path) -> None:
    """Create a video from a static image with the specified duration."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path.as_posix(),
        "-t", f"{duration:.6f}",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",  # Ensure even dimensions
        *H264_SETTINGS,
        dest.as_posix(),
    ]
    run_cmd(cmd)


def extract_audio_segment(
    audio_path: Path,
    start_time: float,
    end_time: float,
    dest: Path,
) -> None:
    """Extract a segment from an audio file.

    Args:
        audio_path: Source audio file
        start_time: Start time in seconds
        end_time: End time in seconds
        dest: Output path
    """
    duration = end_time - start_time
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", audio_path.as_posix(),
        "-ss", f"{start_time:.6f}",
        "-t", f"{duration:.6f}",
        *AAC_SETTINGS,
        dest.as_posix(),
    ]
    run_cmd(cmd)


def concat_audio(input_files: List[Path], output_path: Path, reencode: bool = True) -> None:
    """Concatenate audio files in order.

    Args:
        input_files: List of audio file paths
        output_path: Output path
        reencode: If True, re-encode to avoid codec mismatch issues
    """
    if not input_files:
        raise ValueError("No audio files provided to concatenate")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in input_files:
            p = Path(p)
            abs_path = p if p.is_absolute() else p.resolve()
            f.write(f"file '{abs_path.as_posix()}'\n")
        list_file = f.name

    try:
        if reencode:
            # Choose codec based on output format
            ext = output_path.suffix.lower()
            if ext in (".aac", ".m4a"):
                codec_args = ["-c:a", "aac", "-b:a", "192k"]
            elif ext == ".wav":
                codec_args = ["-c:a", "pcm_s16le"]
            else:
                # Default to MP3 for .mp3 and other formats
                codec_args = ["-c:a", "libmp3lame", "-b:a", "128k"]
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", list_file,
                *codec_args,
                output_path.as_posix(),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", list_file,
                "-c", "copy",
                output_path.as_posix(),
            ]
        run_cmd(cmd)
    finally:
        Path(list_file).unlink(missing_ok=True)


# Backwards compatibility - export old function names
get_duration = probe_duration


# ============================================================================
# ASYNC VERSIONS - For parallel processing in Stage 3
# ============================================================================

async def run_cmd_async(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command asynchronously using asyncio subprocess.

    Args:
        cmd: Command and arguments
        check: If True, raise on non-zero exit code

    Returns:
        CompletedProcess-like result

    Raises:
        RuntimeError: If check=True and command fails
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    # Create a CompletedProcess-like object
    class AsyncResult:
        def __init__(self, returncode, stdout, stderr):
            self.returncode = returncode
            self.stdout = stdout.decode() if stdout else ""
            self.stderr = stderr.decode() if stderr else ""

    result = AsyncResult(process.returncode, stdout, stderr)

    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result


async def probe_duration_async(path: Path) -> float:
    """Get duration of a media file in seconds using ffprobe (async version)."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path.as_posix(),
    ]
    result = await run_cmd_async(cmd)
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"Unable to parse duration from ffprobe output: {result.stdout}") from exc


async def extend_video_async(video_path: Path, extra_seconds: float, dest: Path) -> None:
    """Extend video by freezing the last frame for extra_seconds (async version)."""
    filter_str = f"[0:v]tpad=stop_mode=clone:stop_duration={extra_seconds:.6f},setpts=PTS-STARTPTS[v]"
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path.as_posix(),
        "-filter_complex", filter_str,
        "-map", "[v]",
        "-an",
        *H264_SETTINGS,
        dest.as_posix(),
    ]
    await run_cmd_async(cmd)


async def trim_video_async(video_path: Path, duration: float, dest: Path) -> None:
    """Trim video to specified duration using stream copy (async version)."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path.as_posix(),
        "-t", f"{duration:.6f}",
        "-c", "copy",
        dest.as_posix(),
    ]
    await run_cmd_async(cmd)


async def change_video_speed_async(video_path: Path, speed_multiplier: float, dest: Path) -> None:
    """Change playback speed for a video (async version). speed_multiplier > 1 speeds up."""
    if speed_multiplier <= 0:
        raise ValueError("speed_multiplier must be > 0")
    filter_str = f"setpts=PTS/{speed_multiplier:.6f}"
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path.as_posix(),
        "-an",
        "-filter:v", filter_str,
        *H264_SETTINGS,
        dest.as_posix(),
    ]
    await run_cmd_async(cmd)


async def overlay_audio_async(
    video_path: Path,
    audio_path: Path,
    dest: Path,
    pad_audio_to_video: bool = False,
) -> None:
    """Overlay audio onto video (async version)."""
    if pad_audio_to_video:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path.as_posix(),
            "-i", audio_path.as_posix(),
            "-filter_complex", "[1:a]apad[a]",
            "-map", "0:v:0",
            "-map", "[a]",
            "-c:v", "copy",
            *AAC_SETTINGS,
            "-movflags", "+faststart",
            "-shortest",
            dest.as_posix(),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path.as_posix(),
            "-i", audio_path.as_posix(),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            *AAC_SETTINGS,
            "-movflags", "+faststart",
            "-shortest",
            dest.as_posix(),
        ]
    await run_cmd_async(cmd)


async def overlay_combined_audio_async(
    video_path: Path,
    narration_path: Path,
    dest: Path,
    sfx_audio_source: Optional[Path] = None,
    narration_volume: float = 1.0,
    video_audio_volume: float = 0.3,
    pad_narration: bool = True,
) -> None:
    """Overlay video with combined audio (model-generated SFX + narration) - async version."""
    audio_source = sfx_audio_source if sfx_audio_source else video_path

    if sfx_audio_source:
        filter_complex = (
            f"[1:a]apad,volume={video_audio_volume}[vaud];"
            f"[2:a]apad,volume={narration_volume}[narr];"
            f"[vaud][narr]amix=inputs=2:duration=longest:dropout_transition=0[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path.as_posix(),
            "-i", audio_source.as_posix(),
            "-i", narration_path.as_posix(),
            "-filter_complex", filter_complex,
            "-map", "0:v:0",
            "-map", "[out]",
            "-c:v", "copy",
            *AAC_SETTINGS,
            "-movflags", "+faststart",
            "-shortest",
            dest.as_posix(),
        ]
    else:
        filter_complex = (
            f"[0:a]apad,volume={video_audio_volume}[vaud];"
            f"[1:a]apad,volume={narration_volume}[narr];"
            f"[vaud][narr]amix=inputs=2:duration=longest:dropout_transition=0[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path.as_posix(),
            "-i", narration_path.as_posix(),
            "-filter_complex", filter_complex,
            "-map", "0:v:0",
            "-map", "[out]",
            "-c:v", "copy",
            *AAC_SETTINGS,
            "-movflags", "+faststart",
            "-shortest",
            dest.as_posix(),
        ]
    await run_cmd_async(cmd)


async def image_to_video_async(image_path: Path, duration: float, dest: Path) -> None:
    """Create a video from a static image with the specified duration (async version)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path.as_posix(),
        "-t", f"{duration:.6f}",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        *H264_SETTINGS,
        dest.as_posix(),
    ]
    await run_cmd_async(cmd)


async def concat_videos_async(paths: Iterable[Path], dest: Path, *, reencode: bool = False) -> None:
    """Concatenate multiple videos into one (async version)."""
    paths = list(paths)
    if not paths:
        raise ValueError("No videos provided to concatenate")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as list_file:
        for p in paths:
            p = Path(p)
            abs_path = p if p.is_absolute() else p.resolve()
            if not abs_path.exists():
                raise FileNotFoundError(f"Video not found for concatenation: {abs_path}")
            list_file.write(f"file '{abs_path.as_posix()}'\n")
        concat_list = list_file.name

    try:
        if reencode:
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                *H264_SETTINGS,
                *AAC_SETTINGS,
                "-movflags", "+faststart",
                dest.as_posix(),
            ]
            await run_cmd_async(cmd)
        else:
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                dest.as_posix(),
            ]
            try:
                await run_cmd_async(cmd)
            except RuntimeError:
                await concat_videos_async(paths, dest, reencode=True)
    finally:
        Path(concat_list).unlink(missing_ok=True)
