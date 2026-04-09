"""Timeline JSON parser.

Loads timeline JSON files or dicts into the Timeline data model.
This is the primary public API for loading timelines — other code should
call ``parse_timeline()`` and get back a fully-constructed Timeline object.
"""

import json
import sys
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from timeline.model import (
    Clip,
    Defaults,
    FileSource,
    Generate,
    ImageDefaults,
    ImageSource,
    Output,
    OutputVariants,
    Project,
    Ref,
    SilenceSource,
    Source,
    StillSource,
    TTSDefaults,
    TTSSource,
    Timeline,
    Track,
    VideoDefaults,
    VideoSource,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class TimelineParseError(Exception):
    """Raised when a timeline cannot be parsed."""

    def __init__(self, message: str, path: str = "", errors: Optional[List[str]] = None):
        self.path = path
        self.errors = errors or []
        super().__init__(message)


# ---------------------------------------------------------------------------
# Canonical name enforcement (REQ-PARSE-009)
# ---------------------------------------------------------------------------

_ALIAS_MAP: Dict[str, str] = {
    "first_frame_image": "Use 'first_frame' instead",
    "last_frame_image": "Use 'last_frame' instead",
    "image_paths": "Use 'reference_images' instead",
    "start_image": "Use 'first_frame' instead",
    "end_image": "Use 'last_frame' instead",
    "image_input": "Use 'reference_images' instead",
}


# ---------------------------------------------------------------------------
# Known fields per object type (REQ-PARSE-010)
# ---------------------------------------------------------------------------

_TOP_LEVEL_FIELDS = {"version", "project", "defaults", "assets", "tracks", "output"}

_PROJECT_FIELDS = {"name", "description", "aspect_ratio", "resolution"}

_TRACK_FIELDS = {"id", "type", "clips", "volume"}

_CLIP_FIELDS = {"id", "source", "start_time", "duration", "fit_to", "fit_method", "buffer_ms", "label"}

_SOURCE_FIELDS_BY_TYPE: Dict[str, set] = {
    "image": {"type", "prompt", "reference_images", "model", "aspect_ratio", "resolution",
              "output_format", "safety_filter_level", "candidates", "select", "verify"},
    "video": {"type", "prompt", "first_frame", "last_frame", "model", "duration",
              "aspect_ratio", "resolution", "generate_audio", "negative_prompt", "seed",
              "quality", "reference_images", "reference_videos", "reference_audios",
              "candidates", "select", "verify"},
    "tts": {"type", "text", "voice", "voice_prompt", "model", "candidates", "select"},
    "file": {"type", "path", "start", "end"},
    "silence": {"type", "duration"},
    "still": {"type", "image", "duration"},
}

_DEFAULTS_FIELDS = {"video", "image", "tts"}

_VIDEO_DEFAULTS_FIELDS = {f.name for f in dc_fields(VideoDefaults)}
_IMAGE_DEFAULTS_FIELDS = {f.name for f in dc_fields(ImageDefaults)}
_TTS_DEFAULTS_FIELDS = {f.name for f in dc_fields(TTSDefaults)}

_OUTPUT_FIELDS = {"format", "audio_mix", "variants", "narration_volume", "sfx_volume"}

# Max file size: 1MB
_MAX_FILE_SIZE = 1_048_576


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_timeline(source: Union[str, Path, dict]) -> Timeline:
    """Parse a timeline from a file path or dict.

    Args:
        source: A file path (str or Path) to a JSON file, or a dict.

    Returns:
        A fully-constructed Timeline object.

    Raises:
        TimelineParseError: On parsing errors.
    """
    warnings: List[str] = []

    if isinstance(source, dict):
        raw = source
    elif not isinstance(source, (str, Path)):
        raise TimelineParseError("Timeline must be a JSON object", path="")
    else:
        path = Path(source)
        # Check file size
        try:
            size = path.stat().st_size
        except OSError as e:
            raise TimelineParseError(f"Cannot read timeline file: {e}", path=str(path))
        if size > _MAX_FILE_SIZE:
            raise TimelineParseError(
                f"Timeline file exceeds maximum size of {_MAX_FILE_SIZE} bytes ({size} bytes)",
                path=str(path),
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise TimelineParseError(f"Invalid JSON: {e}", path=str(path))

    if not isinstance(raw, dict):
        raise TimelineParseError("Timeline must be a JSON object", path="")

    # Check for aliases at top level
    _check_aliases(raw, "")

    # Unknown field detection at top level
    _check_unknown_fields(raw, _TOP_LEVEL_FIELDS, "", warnings)

    # Version gate (REQ-PARSE-003)
    version = raw.get("version")
    if version is None:
        raise TimelineParseError("Missing required field: 'version'", path="version")
    if version != 1:
        raise TimelineParseError(
            f"Unsupported timeline version: {version}. Only version 1 is supported.",
            path="version",
        )

    # Required top-level fields (REQ-PARSE-004)
    missing = [f for f in ("project", "tracks") if f not in raw]
    if missing:
        fields_str = ", ".join(f"'{f}'" for f in missing)
        raise TimelineParseError(
            f"Missing required field(s): {fields_str}",
            path=", ".join(missing),
        )

    # Parse sections
    project = _parse_project(raw["project"], warnings)
    defaults = _parse_defaults(raw.get("defaults", {}), warnings)
    assets = _parse_assets(raw.get("assets", {}), defaults, warnings)
    tracks = _parse_tracks(raw["tracks"], defaults, warnings)
    output = _parse_output(raw.get("output", {}), warnings)

    timeline = Timeline(
        version=version,
        project=project,
        defaults=defaults,
        assets=assets,
        tracks=tracks,
        output=output,
    )

    # Attach warnings to the timeline for downstream consumers
    timeline._warnings = warnings  # type: ignore[attr-defined]

    # Print warnings to stderr
    if warnings:
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)

    return timeline


def get_warnings(timeline: Timeline) -> List[str]:
    """Retrieve parser warnings attached to a parsed timeline."""
    return getattr(timeline, "_warnings", [])


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------

def _parse_project(raw: Any, warnings: List[str]) -> Project:
    """Parse the project section (REQ-PARSE-005)."""
    json_path = "project"
    if not isinstance(raw, dict):
        raise TimelineParseError("'project' must be an object", path=json_path)

    _check_unknown_fields(raw, _PROJECT_FIELDS, json_path, warnings)

    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise TimelineParseError(
            "'project.name' is required and must be a non-empty string",
            path=f"{json_path}.name",
        )

    return Project(
        name=name,
        description=raw.get("description"),
        aspect_ratio=raw.get("aspect_ratio", "16:9"),
        resolution=raw.get("resolution", "720p"),
    )


def _parse_defaults(raw: Any, warnings: List[str]) -> Defaults:
    """Parse the defaults section (REQ-PARSE-006)."""
    if not raw:
        return Defaults()
    if not isinstance(raw, dict):
        raise TimelineParseError("'defaults' must be an object", path="defaults")

    _check_unknown_fields(raw, _DEFAULTS_FIELDS, "defaults", warnings)

    video_raw = raw.get("video", {})
    image_raw = raw.get("image", {})
    tts_raw = raw.get("tts", {})

    if video_raw:
        _check_unknown_fields(video_raw, _VIDEO_DEFAULTS_FIELDS, "defaults.video", warnings)
    if image_raw:
        _check_unknown_fields(image_raw, _IMAGE_DEFAULTS_FIELDS, "defaults.image", warnings)
    if tts_raw:
        _check_unknown_fields(tts_raw, _TTS_DEFAULTS_FIELDS, "defaults.tts", warnings)

    video_defaults = VideoDefaults(
        model=video_raw.get("model", "seedance-2.0-fast"),
        duration=video_raw.get("duration", 5),
        generate_audio=video_raw.get("generate_audio", True),
        aspect_ratio=video_raw.get("aspect_ratio", "16:9"),
        resolution=video_raw.get("resolution", "480p"),
        verify=video_raw.get("verify"),
    )

    image_defaults = ImageDefaults(
        model=image_raw.get("model", "nano-banana-pro"),
        aspect_ratio=image_raw.get("aspect_ratio", "16:9"),
        resolution=image_raw.get("resolution", "2K"),
        output_format=image_raw.get("output_format", "png"),
        reference_images=image_raw.get("reference_images", []),
        safety_filter_level=image_raw.get("safety_filter_level", "block_only_high"),
        verify=image_raw.get("verify"),
    )

    tts_defaults = TTSDefaults(
        voice=tts_raw.get("voice", "Kore"),
        model=tts_raw.get("model", "gemini-2.5-flash-tts"),
        voice_prompt=tts_raw.get("voice_prompt"),
    )

    return Defaults(video=video_defaults, image=image_defaults, tts=tts_defaults)


def _parse_assets(raw: Any, defaults: Defaults, warnings: List[str]) -> Dict[str, Source]:
    """Parse the assets section."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise TimelineParseError("'assets' must be an object", path="assets")

    assets: Dict[str, Source] = {}
    for key, value in raw.items():
        json_path = f"assets.{key}"
        if not isinstance(value, dict):
            raise TimelineParseError(f"Asset '{key}' must be an object", path=json_path)
        source = _parse_source(value, json_path, defaults, warnings)
        assets[key] = source

    return assets


def _parse_tracks(raw: Any, defaults: Defaults, warnings: List[str]) -> List[Track]:
    """Parse the tracks array."""
    if not isinstance(raw, list):
        raise TimelineParseError("'tracks' must be an array", path="tracks")

    tracks: List[Track] = []
    for i, track_raw in enumerate(raw):
        json_path = f"tracks[{i}]"
        if not isinstance(track_raw, dict):
            raise TimelineParseError(f"Track must be an object", path=json_path)

        _check_aliases(track_raw, json_path)
        _check_unknown_fields(track_raw, _TRACK_FIELDS, json_path, warnings)

        track_id = track_raw.get("id", "")
        track_type = track_raw.get("type", "")

        clips_raw = track_raw.get("clips", [])
        if not isinstance(clips_raw, list):
            raise TimelineParseError("'clips' must be an array", path=f"{json_path}.clips")

        clips: List[Clip] = []
        for j, clip_raw in enumerate(clips_raw):
            clip_path = f"{json_path}.clips[{j}]"
            clip = _parse_clip(clip_raw, clip_path, defaults, warnings)
            clips.append(clip)

        volume = track_raw.get("volume")
        if volume is not None:
            if not isinstance(volume, (int, float)) or volume < 0.0 or volume > 1.0:
                raise TimelineParseError(
                    "Track 'volume' must be a number between 0.0 and 1.0",
                    path=f"{json_path}.volume",
                )
            volume = float(volume)

        tracks.append(Track(id=track_id, type=track_type, clips=clips, volume=volume))

    return tracks


def _parse_clip(raw: Any, json_path: str, defaults: Defaults, warnings: List[str]) -> Clip:
    """Parse a single clip."""
    if not isinstance(raw, dict):
        raise TimelineParseError("Clip must be an object", path=json_path)

    _check_aliases(raw, json_path)
    _check_unknown_fields(raw, _CLIP_FIELDS, json_path, warnings)

    source_raw = raw.get("source")
    source_path = f"{json_path}.source"

    source: Optional[Source] = None
    if source_raw is not None:
        if not isinstance(source_raw, dict):
            raise TimelineParseError("Clip source must be an object", path=source_path)
        source = _parse_source(source_raw, source_path, defaults, warnings)

    duration = raw.get("duration", "auto")

    return Clip(
        id=raw.get("id", ""),
        source=source,
        start_time=raw.get("start_time"),
        duration=duration,
        fit_to=raw.get("fit_to"),
        fit_method=raw.get("fit_method", "speed"),
        buffer_ms=raw.get("buffer_ms", 0.0),
        label=raw.get("label"),
    )


def _parse_output(raw: Any, warnings: List[str]) -> Output:
    """Parse the output section."""
    if not raw:
        return Output()
    if not isinstance(raw, dict):
        raise TimelineParseError("'output' must be an object", path="output")

    _check_unknown_fields(raw, _OUTPUT_FIELDS, "output", warnings)

    # Parse variants
    variants_raw = raw.get("variants", {})
    variants = OutputVariants()
    if isinstance(variants_raw, dict):
        if "narration_only" in variants_raw:
            variants.narration_only = bool(variants_raw["narration_only"])
        if "narration_sfx" in variants_raw:
            variants.narration_sfx = bool(variants_raw["narration_sfx"])
        if "images_only" in variants_raw:
            variants.images_only = bool(variants_raw["images_only"])

    narration_volume = raw.get("narration_volume", 1.0)
    sfx_volume = raw.get("sfx_volume", 0.3)

    return Output(
        format=raw.get("format", "mp4"),
        variants=variants,
        narration_volume=float(narration_volume),
        sfx_volume=float(sfx_volume),
        audio_mix=raw.get("audio_mix"),
    )


# ---------------------------------------------------------------------------
# Source parsing
# ---------------------------------------------------------------------------

def _parse_source(raw: dict, json_path: str, defaults: Defaults, warnings: List[str]) -> Source:
    """Parse a source object, dispatching by type field."""
    _check_aliases(raw, json_path)

    source_type = raw.get("type")
    if source_type is None:
        raise TimelineParseError("Source missing required 'type' field", path=json_path)

    known_fields = _SOURCE_FIELDS_BY_TYPE.get(source_type)
    if known_fields is None:
        raise TimelineParseError(
            f"Unknown source type: '{source_type}'. "
            f"Valid types: image, video, tts, file, silence, still",
            path=f"{json_path}.type",
        )

    _check_unknown_fields(raw, known_fields, json_path, warnings)

    if source_type == "image":
        return _parse_image_source(raw, json_path, defaults.image)
    elif source_type == "video":
        return _parse_video_source(raw, json_path, defaults.video, defaults)
    elif source_type == "tts":
        return _parse_tts_source(raw, json_path, defaults.tts)
    elif source_type == "file":
        return _parse_file_source(raw, json_path)
    elif source_type == "silence":
        return _parse_silence_source(raw, json_path)
    elif source_type == "still":
        return _parse_still_source(raw, json_path)
    else:
        raise TimelineParseError(f"Unknown source type: '{source_type}'", path=f"{json_path}.type")


def _parse_ref_image_item(value: Any, json_path: str) -> Union[str, Ref]:
    """Parse a single reference_images entry — string path or {"ref": "..."}."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and "ref" in value:
        return Ref(ref=value["ref"], extract=value.get("extract"))
    raise TimelineParseError(
        "reference_images entries must be a file path string or {\"ref\": \"clip_id\"}",
        path=json_path,
    )


def _parse_reference_images(raw_list: Any, json_path: str) -> list:
    """Parse a reference_images list, supporting both strings and Ref objects."""
    if not raw_list:
        return []
    return [_parse_ref_image_item(item, f"{json_path}[{i}]") for i, item in enumerate(raw_list)]


def _parse_ref_video_item(value: Any, json_path: str) -> Union[str, Ref]:
    """Parse a single reference_videos entry — string path or {"ref": "..."}."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and "ref" in value:
        return Ref(ref=value["ref"], extract=value.get("extract"))
    raise TimelineParseError(
        "reference_videos entries must be a file path string or {\"ref\": \"clip_id\"}",
        path=json_path,
    )


def _parse_reference_videos(raw_list: Any, json_path: str) -> list:
    """Parse a reference_videos list, supporting both strings and Ref objects."""
    if not raw_list:
        return []
    return [_parse_ref_video_item(item, f"{json_path}[{i}]") for i, item in enumerate(raw_list)]


def _parse_image_source(raw: dict, json_path: str, img_defaults: ImageDefaults) -> ImageSource:
    """Parse an image source, applying defaults for unset fields."""
    if "reference_images" in raw:
        ref_images = _parse_reference_images(raw["reference_images"], f"{json_path}.reference_images")
    else:
        ref_images = img_defaults.reference_images
    return ImageSource(
        prompt=raw.get("prompt", ""),
        reference_images=ref_images,
        model=raw.get("model", img_defaults.model),
        aspect_ratio=raw.get("aspect_ratio", img_defaults.aspect_ratio),
        resolution=raw.get("resolution", img_defaults.resolution),
        output_format=raw.get("output_format", img_defaults.output_format),
        safety_filter_level=raw.get("safety_filter_level", img_defaults.safety_filter_level),
        candidates=raw.get("candidates"),
        select=raw.get("select"),
        verify=raw.get("verify") if "verify" in raw else img_defaults.verify,
    )


def _parse_video_source(raw: dict, json_path: str, vid_defaults: VideoDefaults, defaults: Defaults = None) -> VideoSource:
    """Parse a video source, applying defaults for unset fields."""
    frame_defaults = defaults or Defaults()

    # Parse reference_images — supports strings and Ref objects
    if "reference_images" in raw:
        ref_images = _parse_reference_images(raw["reference_images"], f"{json_path}.reference_images")
    else:
        ref_images = []

    # Parse reference_videos — supports strings and Ref objects (for video-to-video chaining)
    if "reference_videos" in raw:
        ref_videos = _parse_reference_videos(raw["reference_videos"], f"{json_path}.reference_videos")
    else:
        ref_videos = []

    return VideoSource(
        prompt=raw.get("prompt", ""),
        first_frame=_parse_frame_input(raw.get("first_frame"), f"{json_path}.first_frame", frame_defaults),
        last_frame=_parse_frame_input(raw.get("last_frame"), f"{json_path}.last_frame", frame_defaults),
        model=raw.get("model", vid_defaults.model),
        duration=raw.get("duration", vid_defaults.duration),
        aspect_ratio=raw.get("aspect_ratio", vid_defaults.aspect_ratio),
        resolution=raw.get("resolution", vid_defaults.resolution),
        generate_audio=raw.get("generate_audio", vid_defaults.generate_audio),
        negative_prompt=raw.get("negative_prompt"),
        seed=raw.get("seed"),
        quality=raw.get("quality"),
        reference_images=ref_images,
        reference_videos=ref_videos,
        reference_audios=raw.get("reference_audios", []),
        candidates=raw.get("candidates"),
        select=raw.get("select"),
        verify=raw.get("verify") if "verify" in raw else vid_defaults.verify,
    )


def _parse_tts_source(raw: dict, json_path: str, tts_defaults: TTSDefaults) -> TTSSource:
    """Parse a TTS source, applying defaults for unset fields."""
    return TTSSource(
        text=raw.get("text", ""),
        voice=raw.get("voice", tts_defaults.voice),
        voice_prompt=raw.get("voice_prompt", tts_defaults.voice_prompt),
        model=raw.get("model", tts_defaults.model),
        candidates=raw.get("candidates"),
        select=raw.get("select"),
    )


def _parse_file_source(raw: dict, json_path: str) -> FileSource:
    """Parse a file source."""
    return FileSource(
        path=raw.get("path", ""),
        start=raw.get("start"),
        end=raw.get("end"),
    )


def _parse_silence_source(raw: dict, json_path: str) -> SilenceSource:
    """Parse a silence source."""
    return SilenceSource(
        duration=raw.get("duration", 0.0),
    )


def _parse_still_source(raw: dict, json_path: str) -> StillSource:
    """Parse a still source."""
    image_raw = raw.get("image", "")
    if isinstance(image_raw, dict) and "ref" in image_raw:
        image = Ref(ref=image_raw["ref"], extract=image_raw.get("extract"))
    else:
        image = image_raw

    return StillSource(
        image=image,
        duration=raw.get("duration", 0.0),
    )


# ---------------------------------------------------------------------------
# Frame input parsing (Ref / Generate / string / None)
# ---------------------------------------------------------------------------

def _parse_frame_input(value: Any, json_path: str, defaults: Defaults = None):
    """Parse a first_frame or last_frame value.

    Returns str, Ref, Generate, or None.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "ref" in value:
            return Ref(ref=value["ref"], extract=value.get("extract"))
        if "generate" in value:
            gen_raw = value["generate"]
            if not isinstance(gen_raw, dict):
                raise TimelineParseError(
                    "'generate' value must be a source object",
                    path=f"{json_path}.generate",
                )
            inner_source = _parse_source(gen_raw, f"{json_path}.generate", defaults or Defaults(), [])
            return Generate(generate=inner_source)
        raise TimelineParseError(
            f"Invalid frame input: dict must have 'ref' or 'generate' key",
            path=json_path,
        )
    raise TimelineParseError(
        f"Invalid frame input: expected string, ref object, generate object, or null",
        path=json_path,
    )


# ---------------------------------------------------------------------------
# Alias & unknown field helpers
# ---------------------------------------------------------------------------

def _check_aliases(raw: dict, json_path: str) -> None:
    """Check for known non-canonical aliases and reject with helpful message."""
    for key in raw:
        if key in _ALIAS_MAP:
            full_path = f"{json_path}.{key}" if json_path else key
            raise TimelineParseError(
                f"Non-canonical field name '{key}' at '{full_path}'. {_ALIAS_MAP[key]}",
                path=full_path,
            )


def _check_unknown_fields(
    raw: dict, known: set, json_path: str, warnings: List[str]
) -> None:
    """Warn about unknown fields. Silently ignore _-prefixed fields."""
    for key in raw:
        if key.startswith("_"):
            continue  # Silently ignored
        if key not in known:
            full_path = f"{json_path}.{key}" if json_path else key
            warnings.append(f"Unknown field '{key}' at '{full_path}'")
