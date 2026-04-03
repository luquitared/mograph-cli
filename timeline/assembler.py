"""Timeline assembly pipeline.

Assembles final output variants from generated clips by concatenating
video/audio tracks and mixing them according to the output configuration.
"""

import logging
import shutil
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from timeline.model import Clip, NodeResult, Timeline, Track
from timeline.timing import ClipLayout, TimelineLayout

import shared.media as media

logger = logging.getLogger(__name__)


async def _concat_audio_async(paths: List[Path], dest: Path) -> Path:
    media.concat_audio(paths, dest)
    return dest


async def assemble_timeline(
    timeline: Timeline,
    results: Dict[str, NodeResult],
    layout: TimelineLayout,
    run_dir: Path,
) -> Dict[str, Path]:
    """Assemble final output variants from generated clips.

    Returns dict of variant_name -> output_path, e.g.:
    {"narration_only": Path("final/final.mp4"), "narration_sfx": Path("final/final_with_sfx.mp4")}
    """
    final_dir = run_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)

    # Collect clips by track type
    video_clips, narration_clips, audio_tracks = _collect_clips_by_type(timeline)

    # Concat video track
    video_concat = await _concat_video_track(video_clips, results, final_dir)

    # Concat narration track
    narration_concat = await _concat_narration_track(narration_clips, results, final_dir)

    outputs: Dict[str, Path] = {}
    output_cfg = timeline.output

    # Narration-only variant (REQ-ASSM-003)
    if output_cfg.variants.narration_only and video_concat and narration_concat:
        dest = final_dir / "final.mp4"
        await media.overlay_audio_async(video_concat, narration_concat, dest)
        outputs["narration_only"] = dest
        logger.info("Produced narration-only variant: %s", dest)

    # Narration + SFX variant (REQ-ASSM-004)
    if output_cfg.variants.narration_sfx and video_concat and narration_concat:
        sfx_concat = await _extract_and_concat_sfx(video_clips, run_dir, final_dir)
        dest = final_dir / "final_with_sfx.mp4"
        if sfx_concat:
            await media.overlay_combined_audio_async(
                video_concat,
                narration_concat,
                dest,
                veo_audio_source=sfx_concat,
                narration_volume=output_cfg.narration_volume,
                video_audio_volume=output_cfg.sfx_volume,
            )
        else:
            # No SFX available, fall back to narration-only
            await media.overlay_audio_async(video_concat, narration_concat, dest)
        outputs["narration_sfx"] = dest
        logger.info("Produced narration+sfx variant: %s", dest)

    # Images-only variant (REQ-ASSM-005)
    if output_cfg.variants.images_only and video_clips and narration_concat:
        images_video = await _build_images_only_video(
            video_clips, results, layout, run_dir, final_dir
        )
        if images_video:
            dest = final_dir / "final_images_only.mp4"
            await media.overlay_audio_async(images_video, narration_concat, dest)
            outputs["images_only"] = dest
            logger.info("Produced images-only variant: %s", dest)

    # Audio track mixing (REQ-ASSM-009, REQ-ASSM-010)
    if audio_tracks:
        await _mix_audio_tracks(audio_tracks, results, final_dir, outputs)

    return outputs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _concat_or_copy(
    paths: List[Path], dest: Path, concat_fn: Callable[[List[Path], Path], Awaitable[Path]]
) -> Optional[Path]:
    """Concat multiple paths, copy if single, return None if empty."""
    if not paths:
        return None
    if len(paths) == 1:
        shutil.copy2(paths[0], dest)
        return dest
    await concat_fn(paths, dest)
    return dest


def _collect_clips_by_type(
    timeline: Timeline,
) -> Tuple[List[Tuple[Track, Clip]], List[Tuple[Track, Clip]], List[Track]]:
    """Collect clips grouped by track type, preserving order."""
    video_clips: List[Tuple[Track, Clip]] = []
    narration_clips: List[Tuple[Track, Clip]] = []
    audio_tracks: List[Track] = []

    for track in timeline.tracks:
        if track.type == "video":
            for clip in track.clips:
                video_clips.append((track, clip))
        elif track.type == "narration":
            for clip in track.clips:
                narration_clips.append((track, clip))
        elif track.type == "audio":
            audio_tracks.append(track)

    return video_clips, narration_clips, audio_tracks


async def _concat_video_track(
    video_clips: List[Tuple[Track, Clip]],
    results: Dict[str, NodeResult],
    final_dir: Path,
) -> Optional[Path]:
    """Concat all video clips into a single video (REQ-ASSM-001)."""
    if not video_clips:
        return None

    paths = []
    for _track, clip in video_clips:
        if clip.id in results and results[clip.id].path.exists():
            paths.append(results[clip.id].path)

    dest = final_dir / "video_concat.mp4"
    return await _concat_or_copy(paths, dest, media.concat_videos_async)


async def _concat_narration_track(
    narration_clips: List[Tuple[Track, Clip]],
    results: Dict[str, NodeResult],
    final_dir: Path,
) -> Optional[Path]:
    """Concat all narration clips into a single audio file (REQ-ASSM-002)."""
    if not narration_clips:
        return None

    paths = []
    for _track, clip in narration_clips:
        if clip.id in results and results[clip.id].path.exists():
            paths.append(results[clip.id].path)

    dest = final_dir / "narration_concat.wav"
    return await _concat_or_copy(paths, dest, _concat_audio_async)


async def _extract_and_concat_sfx(
    video_clips: List[Tuple[Track, Clip]],
    run_dir: Path,
    final_dir: Path,
) -> Optional[Path]:
    """Extract audio from original (pre-fit) video files and concat (REQ-ASSM-007, REQ-ASSM-008)."""
    sfx_dir = final_dir / "sfx_parts"
    sfx_dir.mkdir(parents=True, exist_ok=True)

    sfx_paths: List[Path] = []
    for _track, clip in video_clips:
        # Look for original (pre-fit) video in videos/ directory
        original_video = run_dir / "videos" / f"{clip.id}.mp4"
        if not original_video.exists():
            continue

        sfx_dest = sfx_dir / f"{clip.id}_sfx.aac"
        try:
            media.extract_audio_track(original_video, sfx_dest)
            if sfx_dest.exists():
                sfx_paths.append(sfx_dest)
        except Exception:
            logger.warning("Could not extract audio from %s", original_video)

    dest = final_dir / "sfx_concat.aac"
    return await _concat_or_copy(sfx_paths, dest, _concat_audio_async)


async def _build_images_only_video(
    video_clips: List[Tuple[Track, Clip]],
    results: Dict[str, NodeResult],
    layout: TimelineLayout,
    run_dir: Path,
    final_dir: Path,
) -> Optional[Path]:
    """Build a video from still images for each clip (REQ-ASSM-005)."""
    stills_dir = final_dir / "stills"
    stills_dir.mkdir(parents=True, exist_ok=True)

    still_video_paths: List[Path] = []
    for _track, clip in video_clips:
        clip_layout = layout.clips.get(clip.id)
        if not clip_layout:
            continue

        duration = clip_layout.final_duration
        if duration <= 0:
            continue

        # Find image for this clip
        image_path = _find_clip_image(clip, results, run_dir)
        if not image_path:
            continue

        still_dest = stills_dir / f"{clip.id}_still.mp4"
        await media.image_to_video_async(image_path, duration, still_dest)
        still_video_paths.append(still_dest)

    if not still_video_paths:
        return None

    if len(still_video_paths) == 1:
        return still_video_paths[0]

    dest = final_dir / "images_only_concat.mp4"
    await media.concat_videos_async(still_video_paths, dest)
    return dest


def _find_clip_image(
    clip: Clip,
    results: Dict[str, NodeResult],
    run_dir: Path,
) -> Optional[Path]:
    """Find the image corresponding to a video clip."""
    # Check images/ directory for png or jpg
    for ext in (".png", ".jpg"):
        candidate = run_dir / "images" / f"{clip.id}{ext}"
        if candidate.exists():
            return candidate

    # Fallback: extract first frame from generated video
    if clip.id in results and results[clip.id].path.exists():
        video_path = results[clip.id].path
        frame_dest = run_dir / "final" / "stills" / f"{clip.id}_frame.png"
        frame_dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            media.extract_first_frame(video_path, frame_dest)
            if frame_dest.exists():
                return frame_dest
        except Exception:
            logger.warning("Could not extract first frame from %s", video_path)

    return None


async def _mix_audio_tracks(
    audio_tracks: List[Track],
    results: Dict[str, NodeResult],
    final_dir: Path,
    outputs: Dict[str, Path],
) -> None:
    """Mix additional audio tracks into existing output variants (REQ-ASSM-009, REQ-ASSM-010)."""
    for track in audio_tracks:
        audio_paths = []
        for clip in track.clips:
            if clip.id in results and results[clip.id].path.exists():
                audio_paths.append(results[clip.id].path)

        if not audio_paths:
            continue

        # Concat this track's clips
        if len(audio_paths) == 1:
            track_audio = audio_paths[0]
        else:
            track_audio_dest = final_dir / f"audio_track_{track.id}.wav"
            media.concat_audio(audio_paths, track_audio_dest)
            track_audio = track_audio_dest

        volume = track.volume if track.volume is not None else 0.5

        # Mix into each existing output variant
        for variant_name, variant_path in list(outputs.items()):
            mixed_dest = final_dir / f"{variant_path.stem}_mixed_{track.id}.mp4"
            media.combine_audio_tracks(
                variant_path,
                track_audio,
                mixed_dest,
                narration_volume=1.0,
                video_audio_volume=volume,
            )
            # Replace variant with mixed version
            shutil.move(str(mixed_dest), str(variant_path))
