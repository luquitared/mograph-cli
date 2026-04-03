"""Timeline data model package.

Re-exports all public types from timeline.model for convenient imports:

    from timeline import Timeline, Track, Clip, VideoSource
"""

from timeline.model import (
    Clip,
    Defaults,
    FileSource,
    FrameInput,
    Generate,
    ImageDefaults,
    ImageSource,
    NodeResult,
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
    ValidationError,
    ValidationResult,
    VideoDefaults,
    VideoSource,
)

def is_url(value: str) -> bool:
    """Check if a value looks like a URL."""
    return value.startswith("http://") or value.startswith("https://")


__all__ = [
    "Clip",
    "Defaults",
    "is_url",
    "FileSource",
    "FrameInput",
    "Generate",
    "ImageDefaults",
    "ImageSource",
    "NodeResult",
    "Output",
    "OutputVariants",
    "Project",
    "Ref",
    "SilenceSource",
    "Source",
    "StillSource",
    "TTSDefaults",
    "TTSSource",
    "Timeline",
    "Track",
    "ValidationError",
    "ValidationResult",
    "VideoDefaults",
    "VideoSource",
]
