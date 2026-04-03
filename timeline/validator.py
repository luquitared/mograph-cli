"""Timeline validator — two-pass validation for timeline documents.

Pass 1: Static validation (types, required fields, constraints, security).
Pass 2: Dependency validation (DAG construction, cycles, ref targets, type compat).
"""

import difflib
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse

from timeline import is_url
from timeline.dag import build_dag, build_timing_dag, detect_cycles
from timeline.model import (
    Clip,
    FileSource,
    Generate,
    ImageSource,
    Ref,
    SilenceSource,
    Source,
    StillSource,
    TTSSource,
    Timeline,
    Track,
    ValidationError,
    ValidationResult,
    VideoSource,
)
from timeline.security import SecurityError, validate_path, validate_url

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_TRACK_TYPES = {"video", "narration", "audio"}
VALID_SOURCE_TYPES = {"image", "video", "tts", "file", "silence", "still"}
VALID_VIDEO_MODELS = {"veo-3.1", "veo-3.1-fast", "veo-3.1-lite", "kling-v3"}
VEO_MODELS = {"veo-3.1", "veo-3.1-fast", "veo-3.1-lite"}
VEO_DURATIONS = {4, 6, 8}
VALID_IMAGE_FORMATS = {"png", "jpg"}
VALID_EXTRACT_VALUES = {"first_frame", "last_frame", "audio"}
ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

KNOWN_VOICES = [
    "Achernar", "Achird", "Algenib", "Algieba", "Alnilam", "Aoede",
    "Autonoe", "Callirrhoe", "Charon", "Despina", "Enceladus", "Erinome",
    "Fenrir", "Gacrux", "Iapetus", "Kore", "Laomedeia", "Leda", "Orus",
    "Puck", "Pulcherrima", "Rasalgethi", "Sadachbia", "Sadaltager",
    "Schedar", "Sulafat", "Umbriel", "Vindemiatrix", "Zephyr",
]
KNOWN_VOICES_SET = {v.lower() for v in KNOWN_VOICES}

# Input size bounds
MAX_TRACKS = 50
MAX_CLIPS_PER_TRACK = 200
MAX_TOTAL_CLIPS = 500
MAX_CANDIDATES = 20
MAX_GENERATE_NESTING = 2
MAX_PROMPT_BYTES = 10 * 1024  # 10KB


def validate(
    timeline: Timeline, timeline_dir: Optional[Path] = None
) -> ValidationResult:
    """Validate a timeline document in two passes.

    Args:
        timeline: The parsed timeline to validate.
        timeline_dir: Directory containing the timeline file (for resolving
            relative paths). If None, file-existence checks are skipped.

    Returns:
        ValidationResult with all errors and warnings.
    """
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []

    # Pass 1: Static validation
    _validate_static(timeline, timeline_dir, errors, warnings)

    # Pass 2: Dependency validation (only if pass 1 has no errors)
    if not errors:
        _validate_dependencies(timeline, errors, warnings)

    return ValidationResult(errors=errors, warnings=warnings)


# ===========================================================================
# Pass 1 — Static validation
# ===========================================================================

def _validate_static(
    timeline: Timeline,
    timeline_dir: Optional[Path],
    errors: List[ValidationError],
    warnings: List[ValidationError],
) -> None:
    # REQ-SVAL-020: At least one track
    if not timeline.tracks:
        errors.append(ValidationError("tracks", "At least one track is required", "error"))

    # REQ-SVAL-002: Required top-level fields
    if timeline.project is None:
        errors.append(ValidationError("project", "project is required", "error"))
    elif not timeline.project.name:
        errors.append(ValidationError("project.name", "project.name is required", "error"))

    # Input bounds: max tracks
    if len(timeline.tracks) > MAX_TRACKS:
        errors.append(ValidationError(
            "tracks",
            f"Too many tracks: {len(timeline.tracks)} exceeds maximum of {MAX_TRACKS}",
            "error",
        ))

    # Collect all IDs for uniqueness check (REQ-SVAL-003)
    id_locations: Dict[str, List[str]] = {}

    # Asset IDs
    for asset_id, source in timeline.assets.items():
        _track_id(asset_id, f"assets.{asset_id}", id_locations, errors)
        _validate_source(source, f"assets.{asset_id}", timeline_dir, errors, warnings, 0)

    # Track and clip validation
    total_clips = 0
    for ti, track in enumerate(timeline.tracks):
        tp = f"tracks[{ti}]"

        # REQ-SVAL-002: track required fields
        if not track.id:
            errors.append(ValidationError(f"{tp}.id", "track.id is required", "error"))
        elif not ID_PATTERN.match(track.id):
            errors.append(ValidationError(
                f"{tp}.id",
                f"Invalid ID format: '{track.id}'. Must match [a-zA-Z0-9_-]+",
                "error",
            ))

        if not track.type:
            errors.append(ValidationError(f"{tp}.type", "track.type is required", "error"))
        elif track.type not in VALID_TRACK_TYPES:
            errors.append(ValidationError(
                f"{tp}.type",
                f"Invalid track type: '{track.type}'. Must be one of: {', '.join(sorted(VALID_TRACK_TYPES))}",
                "error",
            ))

        # REQ-SVAL-020: each track has at least one clip
        if not track.clips:
            errors.append(ValidationError(f"{tp}.clips", "Track must have at least one clip", "error"))

        # Input bounds: max clips per track
        if len(track.clips) > MAX_CLIPS_PER_TRACK:
            errors.append(ValidationError(
                f"{tp}.clips",
                f"Too many clips in track: {len(track.clips)} exceeds maximum of {MAX_CLIPS_PER_TRACK}",
                "error",
            ))

        total_clips += len(track.clips)

        for ci, clip in enumerate(track.clips):
            cp = f"{tp}.clips[{ci}]"
            _validate_clip(clip, cp, timeline_dir, id_locations, errors, warnings)

    # Input bounds: max total clips
    if total_clips > MAX_TOTAL_CLIPS:
        errors.append(ValidationError(
            "tracks",
            f"Too many total clips: {total_clips} exceeds maximum of {MAX_TOTAL_CLIPS}",
            "error",
        ))

    # REQ-SVAL-003: Report duplicate IDs
    for id_val, locations in id_locations.items():
        if len(locations) > 1:
            errors.append(ValidationError(
                locations[0],
                f"Duplicate ID '{id_val}' found at: {', '.join(locations)}",
                "error",
            ))


def _track_id(
    id_val: str,
    path: str,
    id_locations: Dict[str, List[str]],
    errors: List[ValidationError],
) -> None:
    """Track an ID for uniqueness and validate format."""
    if not id_val:
        return
    # REQ-SVAL-004: ID format
    if not ID_PATTERN.match(id_val):
        errors.append(ValidationError(
            path,
            f"Invalid ID format: '{id_val}'. Must match [a-zA-Z0-9_-]+",
            "error",
        ))
    id_locations.setdefault(id_val, []).append(path)


def _validate_clip(
    clip: Clip,
    path: str,
    timeline_dir: Optional[Path],
    id_locations: Dict[str, List[str]],
    errors: List[ValidationError],
    warnings: List[ValidationError],
) -> None:
    """Validate a single clip."""
    # REQ-SVAL-002: clip required fields
    if not clip.id:
        errors.append(ValidationError(f"{path}.id", "clip.id is required", "error"))
    else:
        _track_id(clip.id, f"{path}.id", id_locations, errors)

    if clip.source is None:
        errors.append(ValidationError(f"{path}.source", "clip.source is required", "error"))
    else:
        _validate_source(clip.source, f"{path}.source", timeline_dir, errors, warnings, 0)


def _validate_source(
    source: Source,
    path: str,
    timeline_dir: Optional[Path],
    errors: List[ValidationError],
    warnings: List[ValidationError],
    nesting_level: int,
) -> None:
    """Validate a source object and its type-specific constraints."""
    # REQ-SVAL-006: source type
    source_type = getattr(source, "type", None)
    if source_type not in VALID_SOURCE_TYPES:
        errors.append(ValidationError(
            f"{path}.type",
            f"Invalid source type: '{source_type}'. Must be one of: {', '.join(sorted(VALID_SOURCE_TYPES))}",
            "error",
        ))
        return

    if isinstance(source, ImageSource):
        _validate_image_source(source, path, timeline_dir, errors, warnings)
    elif isinstance(source, VideoSource):
        _validate_video_source(source, path, timeline_dir, errors, warnings, nesting_level)
    elif isinstance(source, TTSSource):
        _validate_tts_source(source, path, errors, warnings)
    elif isinstance(source, FileSource):
        _validate_file_source(source, path, timeline_dir, errors, warnings)
    elif isinstance(source, SilenceSource):
        _validate_silence_source(source, path, errors)
    elif isinstance(source, StillSource):
        _validate_still_source(source, path, timeline_dir, errors, warnings)


def _validate_image_source(
    source: ImageSource,
    path: str,
    timeline_dir: Optional[Path],
    errors: List[ValidationError],
    warnings: List[ValidationError],
) -> None:
    # REQ-SVAL-002: prompt required
    if not source.prompt:
        errors.append(ValidationError(f"{path}.prompt", "prompt is required for image source", "error"))

    # Input bounds: prompt size
    if source.prompt and len(source.prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        errors.append(ValidationError(
            f"{path}.prompt",
            f"Prompt exceeds maximum size of {MAX_PROMPT_BYTES} bytes",
            "error",
        ))

    # REQ-SVAL-019: output_format
    if source.output_format not in VALID_IMAGE_FORMATS:
        errors.append(ValidationError(
            f"{path}.output_format",
            f"Invalid output_format: '{source.output_format}'. Must be 'png' or 'jpg'",
            "error",
        ))

    # REQ-SVAL-016: candidates non-empty
    _validate_candidates(source, path, errors)

    # REQ-SVAL-014: reference image existence
    for ri, ref_img in enumerate(source.reference_images):
        _validate_file_or_url(ref_img, f"{path}.reference_images[{ri}]", timeline_dir, errors)


def _validate_video_source(
    source: VideoSource,
    path: str,
    timeline_dir: Optional[Path],
    errors: List[ValidationError],
    warnings: List[ValidationError],
    nesting_level: int,
) -> None:
    # REQ-SVAL-002: prompt required
    if not source.prompt:
        errors.append(ValidationError(f"{path}.prompt", "prompt is required for video source", "error"))

    # Input bounds: prompt size
    if source.prompt and len(source.prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        errors.append(ValidationError(
            f"{path}.prompt",
            f"Prompt exceeds maximum size of {MAX_PROMPT_BYTES} bytes",
            "error",
        ))

    # REQ-SVAL-018: video model name
    if source.model not in VALID_VIDEO_MODELS:
        errors.append(ValidationError(
            f"{path}.model",
            f"Invalid video model: '{source.model}'. Must be one of: {', '.join(sorted(VALID_VIDEO_MODELS))}",
            "error",
        ))

    # REQ-SVAL-007: Veo duration
    if source.model in VEO_MODELS:
        if source.duration != "auto" and source.duration is not None:
            if source.duration not in VEO_DURATIONS:
                errors.append(ValidationError(
                    f"{path}.duration",
                    f"Invalid duration {source.duration} for {source.model}. Must be 4, 6, or 8",
                    "error",
                ))

    # REQ-SVAL-008: Veo Fast resolution
    if source.model == "veo-3.1-fast" and source.resolution != "720p":
        errors.append(ValidationError(
            f"{path}.resolution",
            f"veo-3.1-fast only supports 720p resolution, got '{source.resolution}'",
            "error",
        ))

    # REQ-SVAL-009: Veo Quality resolution
    if source.model == "veo-3.1" and source.resolution not in ("720p", "1080p"):
        errors.append(ValidationError(
            f"{path}.resolution",
            f"veo-3.1 supports 720p or 1080p, got '{source.resolution}'",
            "error",
        ))

    # REQ-SVAL-010: Kling resolution
    if source.model == "kling-v3" and source.resolution not in ("720p", "1080p"):
        errors.append(ValidationError(
            f"{path}.resolution",
            f"kling-v3 supports 720p or 1080p, got '{source.resolution}'",
            "error",
        ))

    # REQ-SVAL-011: Veo Lite generate_audio warning
    if source.model == "veo-3.1-lite" and source.generate_audio is False:
        warnings.append(ValidationError(
            f"{path}.generate_audio",
            "generate_audio is ignored for veo-3.1-lite (audio is always generated)",
            "warning",
        ))

    # REQ-SVAL-016: candidates non-empty
    _validate_candidates(source, path, errors)

    # Validate first_frame / last_frame
    _validate_frame_input(source.first_frame, f"{path}.first_frame", timeline_dir, errors, warnings, nesting_level)
    _validate_frame_input(source.last_frame, f"{path}.last_frame", timeline_dir, errors, warnings, nesting_level)


def _validate_frame_input(
    frame_input,
    path: str,
    timeline_dir: Optional[Path],
    errors: List[ValidationError],
    warnings: List[ValidationError],
    nesting_level: int,
) -> None:
    """Validate a first_frame or last_frame value."""
    if frame_input is None:
        return
    if isinstance(frame_input, str):
        # URL or path — validate security
        _validate_file_or_url(frame_input, path, timeline_dir, errors)
    elif isinstance(frame_input, Ref):
        # REQ-DEPV-008: extract values
        if frame_input.extract is not None and frame_input.extract not in VALID_EXTRACT_VALUES:
            errors.append(ValidationError(
                f"{path}.extract",
                f"Invalid extract value: '{frame_input.extract}'. Must be one of: {', '.join(sorted(VALID_EXTRACT_VALUES))}",
                "error",
            ))
    elif isinstance(frame_input, Generate):
        # Max nesting
        if nesting_level >= MAX_GENERATE_NESTING:
            errors.append(ValidationError(
                path,
                f"Generate nesting exceeds maximum depth of {MAX_GENERATE_NESTING}",
                "error",
            ))
        elif frame_input.generate is not None:
            _validate_source(
                frame_input.generate, f"{path}.generate",
                timeline_dir, errors, warnings, nesting_level + 1,
            )


def _validate_tts_source(
    source: TTSSource,
    path: str,
    errors: List[ValidationError],
    warnings: List[ValidationError],
) -> None:
    # REQ-SVAL-002: text required
    if not source.text:
        errors.append(ValidationError(f"{path}.text", "text is required for TTS source", "error"))

    # Input bounds: text size
    if source.text and len(source.text.encode("utf-8")) > MAX_PROMPT_BYTES:
        errors.append(ValidationError(
            f"{path}.text",
            f"Text exceeds maximum size of {MAX_PROMPT_BYTES} bytes",
            "error",
        ))

    # REQ-SVAL-012: voice name
    if source.voice and source.voice.lower() not in KNOWN_VOICES_SET:
        matches = difflib.get_close_matches(source.voice, KNOWN_VOICES, n=1, cutoff=0.5)
        suggestion = f" Did you mean '{matches[0]}'?" if matches else ""
        errors.append(ValidationError(
            f"{path}.voice",
            f"Unknown voice: '{source.voice}'.{suggestion}",
            "error",
        ))

    # REQ-SVAL-016: candidates non-empty
    _validate_candidates(source, path, errors)


def _validate_file_source(
    source: FileSource,
    path: str,
    timeline_dir: Optional[Path],
    errors: List[ValidationError],
    warnings: List[ValidationError],
) -> None:
    # REQ-SVAL-002: path required
    if not source.path:
        errors.append(ValidationError(f"{path}.path", "path is required for file source", "error"))
        return

    _validate_file_or_url(source.path, f"{path}.path", timeline_dir, errors)

    # Extract source_id from path for error messages
    source_id = path.split("(")[-1].rstrip(")") if "(" in path else path

    # For local files, probe duration as a warning
    file_path = source.path
    if timeline_dir and not is_url(file_path):
        full_path = str(Path(timeline_dir) / file_path)
        if os.path.exists(full_path):
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "csv=p=0", full_path],
                    capture_output=True, text=True, timeout=10
                )
                duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0
                if duration <= 0:
                    warnings.append(ValidationError(
                        severity="warning", message=f"Could not determine duration for {file_path}",
                        path=f"file_source({source_id})"
                    ))
            except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
                warnings.append(ValidationError(
                    severity="warning", message=f"ffprobe failed for {file_path}",
                    path=f"file_source({source_id})"
                ))


def _validate_silence_source(
    source: SilenceSource,
    path: str,
    errors: List[ValidationError],
) -> None:
    # REQ-SVAL-002: duration required (check for zero/unset)
    if source.duration <= 0:
        errors.append(ValidationError(
            f"{path}.duration", "duration is required for silence source", "error",
        ))
    # REQ-SVAL-015: minimum 0.1s
    elif source.duration < 0.1:
        errors.append(ValidationError(
            f"{path}.duration",
            f"Silence duration {source.duration}s is below minimum of 0.1s",
            "error",
        ))


def _validate_still_source(
    source: StillSource,
    path: str,
    timeline_dir: Optional[Path],
    errors: List[ValidationError],
    warnings: List[ValidationError],
) -> None:
    # REQ-SVAL-002: image and duration required
    if not source.image:
        errors.append(ValidationError(f"{path}.image", "image is required for still source", "error"))
    elif isinstance(source.image, str):
        _validate_file_or_url(source.image, f"{path}.image", timeline_dir, errors)
    # If Ref, validated in pass 2

    if source.duration <= 0:
        errors.append(ValidationError(
            f"{path}.duration", "duration is required for still source", "error",
        ))


def _validate_candidates(
    source, path: str, errors: List[ValidationError]
) -> None:
    """Validate candidates and select fields."""
    candidates = getattr(source, "candidates", None)
    select = getattr(source, "select", None)

    if candidates is not None:
        # REQ-SVAL-016: non-empty
        if len(candidates) == 0:
            errors.append(ValidationError(
                f"{path}.candidates", "candidates array must not be empty", "error",
            ))
        # Input bounds: max candidates
        if len(candidates) > MAX_CANDIDATES:
            errors.append(ValidationError(
                f"{path}.candidates",
                f"Too many candidates: {len(candidates)} exceeds maximum of {MAX_CANDIDATES}",
                "error",
            ))

    if select is not None:
        # REQ-SVAL-017: select bounds
        if not isinstance(select, int) or select < 1:
            errors.append(ValidationError(
                f"{path}.select", "select must be a positive integer", "error",
            ))
        elif candidates is not None and select > len(candidates):
            errors.append(ValidationError(
                f"{path}.select",
                f"select value {select} exceeds number of candidates ({len(candidates)})",
                "error",
            ))


def _validate_file_or_url(
    value: str,
    path: str,
    timeline_dir: Optional[Path],
    errors: List[ValidationError],
) -> None:
    """Validate a value that is either a URL or a local file path."""
    if is_url(value):
        try:
            validate_url(value)
        except SecurityError as e:
            errors.append(ValidationError(path, f"Security error: {e}", "error"))
    elif timeline_dir is not None:
        # Local file path — resolve relative to CWD
        file_path = Path(timeline_dir) / value
        try:
            validate_path(file_path, Path.cwd())
        except SecurityError as e:
            errors.append(ValidationError(path, f"Security error: {e}", "error"))
            return
        # REQ-SVAL-013: file existence
        if not file_path.exists():
            errors.append(ValidationError(
                path, f"File not found: {value}", "error",
            ))
    else:
        # No timeline_dir (inline timeline) — local file paths not allowed
        errors.append(ValidationError(
            path,
            "Local file paths are not supported with inline timelines. Use a URL instead.",
            "error",
        ))



# ===========================================================================
# Pass 2 — Dependency validation
# ===========================================================================

def _validate_dependencies(
    timeline: Timeline,
    errors: List[ValidationError],
    warnings: List[ValidationError],
) -> None:
    """Validate inter-node dependencies via DAG analysis."""
    # Build full DAG
    dag = build_dag(timeline)

    # REQ-DEPV-007: fit_to timing cycles (check early, independent of full DAG)
    timing_dag = build_timing_dag(timeline)
    timing_cycles = detect_cycles(timing_dag)
    for cycle in timing_cycles:
        errors.append(ValidationError(
            "fit_to",
            f"Timing cycle detected: {' -> '.join(cycle)}",
            "error",
        ))

    # REQ-DEPV-002: Cycle detection (full DAG)
    cycles = detect_cycles(dag)
    for cycle in cycles:
        # Skip if this cycle was already reported as a timing cycle
        errors.append(ValidationError(
            "dependencies",
            f"Dependency cycle detected: {' -> '.join(cycle)}",
            "error",
        ))

    if cycles or timing_cycles:
        return  # Skip further dep validation if cycles exist

    # Build ID -> source mapping for type checking
    source_map: Dict[str, Source] = {}
    for asset_id, source in timeline.assets.items():
        source_map[asset_id] = source
    for track in timeline.tracks:
        for clip in track.clips:
            if clip.id and clip.source:
                source_map[clip.id] = clip.source

    # Build clip lookup for fit_to
    clip_ids: Set[str] = set()
    for track in timeline.tracks:
        for clip in track.clips:
            if clip.id:
                clip_ids.add(clip.id)

    all_ids = set(source_map.keys())

    # Validate each ref and fit_to
    for ti, track in enumerate(timeline.tracks):
        for ci, clip in enumerate(track.clips):
            cp = f"tracks[{ti}].clips[{ci}]"
            if clip.source and isinstance(clip.source, VideoSource):
                _validate_frame_ref(
                    clip.source.first_frame, f"{cp}.source.first_frame",
                    all_ids, source_map, errors,
                )
                _validate_frame_ref(
                    clip.source.last_frame, f"{cp}.source.last_frame",
                    all_ids, source_map, errors,
                )
            if clip.source and isinstance(clip.source, StillSource):
                if isinstance(clip.source.image, Ref):
                    ref = clip.source.image
                    if ref.ref not in all_ids:
                        errors.append(ValidationError(
                            f"{cp}.source.image.ref",
                            f"Ref target '{ref.ref}' does not exist",
                            "error",
                        ))

            # REQ-DEPV-006: fit_to target existence
            if clip.fit_to:
                if clip.fit_to not in clip_ids:
                    errors.append(ValidationError(
                        f"{cp}.fit_to",
                        f"fit_to target '{clip.fit_to}' does not exist",
                        "error",
                    ))

    # REQ-DEPV-010: deep last_frame chains
    _check_deep_chains(timeline, source_map, all_ids, warnings)


def _validate_frame_ref(
    frame_input,
    path: str,
    all_ids: Set[str],
    source_map: Dict[str, Source],
    errors: List[ValidationError],
) -> None:
    """Validate a ref in first_frame or last_frame context."""
    if not isinstance(frame_input, Ref):
        return

    ref = frame_input

    # REQ-DEPV-003: ref target existence
    if ref.ref not in all_ids:
        errors.append(ValidationError(
            f"{path}.ref",
            f"Ref target '{ref.ref}' does not exist",
            "error",
        ))
        return

    target_source = source_map.get(ref.ref)

    if ref.extract in ("first_frame", "last_frame", "audio"):
        # REQ-DEPV-005: extract target must be video
        if target_source and not isinstance(target_source, VideoSource):
            errors.append(ValidationError(
                f"{path}.extract",
                f"extract: '{ref.extract}' requires a video source target, "
                f"but '{ref.ref}' is type '{getattr(target_source, 'type', 'unknown')}'",
                "error",
            ))
    else:
        # REQ-DEPV-004: first_frame/last_frame refs must target image/video producers
        if target_source and not isinstance(
            target_source, (ImageSource, VideoSource, StillSource)
        ):
            errors.append(ValidationError(
                f"{path}",
                f"Ref target '{ref.ref}' does not produce image or video output "
                f"(type: '{getattr(target_source, 'type', 'unknown')}')",
                "error",
            ))
        # REQ-DEPV-004b: video refs require extract to specify which frame
        if target_source and isinstance(target_source, VideoSource):
            errors.append(ValidationError(
                f"{path}",
                f"Ref to video source '{ref.ref}' requires 'extract' field "
                f"(e.g., extract: 'first_frame' or 'last_frame')",
                "error",
            ))


def _check_deep_chains(
    timeline: Timeline,
    source_map: Dict[str, Source],
    all_ids: Set[str],
    warnings: List[ValidationError],
) -> None:
    """Warn if any first_frame or last_frame chain exceeds 10 nodes."""
    # Build frame adjacency: node -> next node via first_frame or last_frame ref
    last_frame_next: Dict[str, str] = {}
    for node_id, source in source_map.items():
        if isinstance(source, VideoSource):
            if isinstance(source.last_frame, Ref):
                last_frame_next[node_id] = source.last_frame.ref
            elif isinstance(source.first_frame, Ref):
                last_frame_next[node_id] = source.first_frame.ref

    # Find chain roots (nodes that depend on something via last_frame
    # but nothing depends on them via last_frame)
    has_incoming: Set[str] = set(last_frame_next.values())

    # Measure chain length starting from each node, using memoization
    chain_length: Dict[str, int] = {}

    def get_chain_length(node_id: str) -> int:
        if node_id in chain_length:
            return chain_length[node_id]
        if node_id not in last_frame_next:
            chain_length[node_id] = 1
            return 1
        length = 1 + get_chain_length(last_frame_next[node_id])
        chain_length[node_id] = length
        return length

    for node_id in last_frame_next:
        length = get_chain_length(node_id)
        if length > 10 and node_id not in has_incoming:
            # Only warn once per chain, from the root
            warnings.append(ValidationError(
                "dependencies",
                f"extract: 'last_frame' chain exceeds 10 nodes ({length})",
                "warning",
            ))
