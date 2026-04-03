"""Timeline timing computation.

Computes the final layout (start_time, final_duration) for every clip in a
timeline after generation has produced media files with known durations.
Pure computation — no media I/O.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from timeline.model import (
    Clip,
    FileSource,
    ImageSource,
    NodeResult,
    SilenceSource,
    StillSource,
    Timeline,
    VideoSource,
)


@dataclass
class ClipLayout:
    clip_id: str
    track_id: str
    start_time: float
    raw_duration: float
    final_duration: float
    fit_to: Optional[str]
    fit_method: str
    buffer_ms: float
    needs_fit: bool


@dataclass
class TimelineLayout:
    clips: Dict[str, ClipLayout]
    track_order: List[str]
    total_duration: float


def _get_raw_duration(clip: Clip, results: Dict[str, NodeResult]) -> float:
    """Determine raw duration for a clip from results or source fields."""
    # If NodeResult has a duration, prefer it
    if clip.id in results and results[clip.id].duration is not None:
        node_dur = results[clip.id].duration
        # If clip duration is "auto", use source/result duration
        if clip.duration == "auto" or clip.duration is None:
            return node_dur
        # If clip has an explicit numeric duration, use it
        if isinstance(clip.duration, (int, float)):
            return float(clip.duration)
        return node_dur

    # Fall back to source-level duration
    source = clip.source
    if source is None:
        if isinstance(clip.duration, (int, float)):
            return float(clip.duration)
        return 0.0

    if isinstance(source, ImageSource):
        return 0.0

    if isinstance(source, VideoSource):
        if isinstance(source.duration, (int, float)):
            dur = float(source.duration)
        else:
            dur = 0.0
        # If clip has explicit numeric duration, it overrides
        if isinstance(clip.duration, (int, float)):
            return float(clip.duration)
        return dur

    if isinstance(source, SilenceSource):
        return source.duration

    if isinstance(source, StillSource):
        return source.duration

    if isinstance(source, FileSource):
        if source.start is not None and source.end is not None:
            return source.end - source.start
        # Check node result
        if clip.id in results and results[clip.id].duration is not None:
            return results[clip.id].duration
        if isinstance(clip.duration, (int, float)):
            return float(clip.duration)
        return 0.0

    # TTSSource or unknown — rely on NodeResult (already checked above)
    if isinstance(clip.duration, (int, float)):
        return float(clip.duration)
    return 0.0


def _build_fit_to_order(
    clips_with_fit: Dict[str, str], all_clip_ids: Set[str]
) -> List[str]:
    """Build topological order for fit_to resolution.

    Args:
        clips_with_fit: mapping of clip_id -> fit_to target clip_id
        all_clip_ids: set of all known clip ids

    Returns:
        List of clip_ids in resolution order (leaves first).

    Raises:
        ValueError: on cycles or references to non-existent clips.
    """
    from timeline.dag import topological_sort_nodes

    for clip_id, target_id in clips_with_fit.items():
        if target_id not in all_clip_ids:
            raise ValueError(
                f"Clip '{clip_id}' has fit_to '{target_id}' which does not exist"
            )

    # Build edges: clip depends on target (only when target also has fit_to)
    nodes = list(clips_with_fit.keys())
    edges = []
    for clip_id, target_id in clips_with_fit.items():
        if target_id in clips_with_fit:
            edges.append((clip_id, target_id))

    levels = topological_sort_nodes(nodes, edges)
    order = [nid for level in levels for nid in level]

    if len(order) != len(nodes):
        raise ValueError("Cycle detected in fit_to dependencies")

    return order


def compute_timeline_timing(
    timeline: Timeline, results: Dict[str, NodeResult]
) -> TimelineLayout:
    """Compute the final layout for every clip in a timeline.

    Args:
        timeline: The timeline with tracks and clips.
        results: Mapping of clip_id -> NodeResult from generation.

    Returns:
        TimelineLayout with computed positions and durations.
    """
    if not timeline.tracks:
        return TimelineLayout(clips={}, track_order=[], total_duration=0.0)

    track_order = [t.id for t in timeline.tracks]
    all_clip_ids: Set[str] = set()
    clip_to_track: Dict[str, str] = {}
    clip_obj: Dict[str, Clip] = {}

    for track in timeline.tracks:
        for clip in track.clips:
            all_clip_ids.add(clip.id)
            clip_to_track[clip.id] = track.id
            clip_obj[clip.id] = clip

    # Step 1: Determine raw durations
    layouts: Dict[str, ClipLayout] = {}
    for clip_id, clip in clip_obj.items():
        raw_dur = _get_raw_duration(clip, results)
        layouts[clip_id] = ClipLayout(
            clip_id=clip_id,
            track_id=clip_to_track[clip_id],
            start_time=0.0,
            raw_duration=raw_dur,
            final_duration=raw_dur,
            fit_to=clip.fit_to,
            fit_method=clip.fit_method,
            buffer_ms=clip.buffer_ms,
            needs_fit=False,
        )

    # Step 1b: Apply buffer_ms to raw_duration (REQ-TIME-009)
    for cid, clip in clip_obj.items():
        if clip.buffer_ms:
            layouts[cid].raw_duration += clip.buffer_ms / 1000.0
            layouts[cid].final_duration = layouts[cid].raw_duration

    # Step 2: Initial sequential placement
    _sequential_placement(timeline, layouts)

    # Step 3 & 4: fit_to resolution
    clips_with_fit = {
        cid: clip.fit_to
        for cid, clip in clip_obj.items()
        if clip.fit_to is not None
    }

    if clips_with_fit:
        # Detect multi-clip fitting: group by (track_id, target)
        track_target_groups: Dict[tuple, List[str]] = defaultdict(list)
        for cid, target in clips_with_fit.items():
            key = (clip_to_track[cid], target)
            track_target_groups[key].append(cid)

        order = _build_fit_to_order(clips_with_fit, all_clip_ids)

        # Track which clips have been handled by multi-clip fitting
        multi_fit_handled: Set[str] = set()

        for clip_id in order:
            if clip_id in multi_fit_handled:
                continue

            target_id = clips_with_fit[clip_id]
            target_layout = layouts[target_id]
            clip = clip_obj[clip_id]

            # Check for multi-clip fitting
            key = (clip_to_track[clip_id], target_id)
            group = track_target_groups[key]

            if len(group) > 1:
                # Multi-clip fitting (REQ-TIME-010)
                target_dur = target_layout.final_duration
                # Distribute target duration proportionally by raw duration
                # (raw_duration already includes buffer from Step 1b)
                total_raw = sum(layouts[cid].raw_duration for cid in group)
                if total_raw > 0:
                    for cid in group:
                        proportion = layouts[cid].raw_duration / total_raw
                        adjusted_dur = target_dur * proportion
                        layouts[cid].final_duration = adjusted_dur
                        layouts[cid].needs_fit = (
                            layouts[cid].raw_duration != adjusted_dur
                        )
                        multi_fit_handled.add(cid)
                else:
                    # Equal distribution if all raw durations are 0
                    each = target_dur / len(group)
                    for cid in group:
                        layouts[cid].final_duration = each
                        layouts[cid].needs_fit = True
                        multi_fit_handled.add(cid)
            else:
                # Single clip fit_to
                target_dur = target_layout.final_duration
                layouts[clip_id].final_duration = target_dur
                layouts[clip_id].needs_fit = (
                    layouts[clip_id].raw_duration != target_dur
                )

                # Start time alignment
                if clip.start_time is None:
                    layouts[clip_id].start_time = target_layout.start_time
                elif clip.start_time < 0:
                    # Negative = relative offset from target
                    layouts[clip_id].start_time = (
                        target_layout.start_time + clip.start_time
                    )

    # Step 5: Recompute sequential placement for non-fit, non-explicit clips
    _recompute_sequential(timeline, layouts, clip_obj, clips_with_fit)

    # Step 6: Compute total duration
    total = 0.0
    for layout in layouts.values():
        end = layout.start_time + layout.final_duration
        if end > total:
            total = end

    return TimelineLayout(clips=layouts, track_order=track_order, total_duration=total)


def _sequential_placement(
    timeline: Timeline, layouts: Dict[str, ClipLayout]
) -> None:
    """Place clips sequentially within each track."""
    for track in timeline.tracks:
        current_time = 0.0
        for clip in track.clips:
            layout = layouts[clip.id]
            if clip.start_time is not None:
                layout.start_time = clip.start_time
            else:
                layout.start_time = current_time
            current_time = layout.start_time + layout.final_duration


def _recompute_sequential(
    timeline: Timeline,
    layouts: Dict[str, ClipLayout],
    clip_obj: Dict[str, Clip],
    clips_with_fit: Dict[str, str],
) -> None:
    """Recompute sequential start_times after fit_to resolution.

    Preserves explicit start_times and fit_to-aligned start_times.
    """
    for track in timeline.tracks:
        current_time = 0.0
        for clip in track.clips:
            layout = layouts[clip.id]
            has_fit_alignment = (
                clip.id in clips_with_fit and clip.start_time is None
            )
            if clip.start_time is not None or has_fit_alignment:
                # Preserve explicit or fit-aligned start_time
                current_time = layout.start_time + layout.final_duration
            else:
                layout.start_time = current_time
                current_time = layout.start_time + layout.final_duration
