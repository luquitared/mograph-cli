"""Timeline data model.

Defines the complete data model for the timeline-based video project format.
Source types use a ``type`` discriminator field for tagged-union dispatch.
All clip and asset IDs share a single flat namespace.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union


# ---------------------------------------------------------------------------
# Source types (tagged union via 'type' field)
# ---------------------------------------------------------------------------

@dataclass
class ImageSource:
    """Image generation source (Replicate Nano Banana Pro)."""
    type: Literal["image"] = "image"
    prompt: str = ""
    reference_images: List[str] = field(default_factory=list)
    model: str = "nano-banana-pro"
    aspect_ratio: str = "16:9"
    resolution: str = "2K"
    output_format: str = "png"
    safety_filter_level: str = "block_only_high"
    candidates: Optional[List[Dict[str, Any]]] = None
    select: Optional[int] = None


@dataclass
class VideoSource:
    """Video generation source (Veo 3.1 / Kling v3 / Seedance 2.0)."""
    type: Literal["video"] = "video"
    prompt: str = ""
    first_frame: Optional[Union[str, "Ref", "Generate"]] = None
    last_frame: Optional[Union[str, "Ref", "Generate"]] = None
    model: str = "veo-3.1-fast"
    duration: Union[int, Literal["auto"], None] = 6
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    generate_audio: bool = True
    negative_prompt: Optional[str] = None
    seed: Optional[int] = None
    quality: Optional[str] = None  # Seedance 2.0: "basic" or "high"
    reference_images: List[str] = field(default_factory=list)  # Kling v3: up to 7 reference images
    candidates: Optional[List[Dict[str, Any]]] = None
    select: Optional[int] = None


@dataclass
class TTSSource:
    """Text-to-speech generation source (Gemini TTS)."""
    type: Literal["tts"] = "tts"
    text: str = ""
    voice: str = "Kore"
    voice_prompt: Optional[str] = None
    model: str = "gemini-2.5-flash-tts"
    candidates: Optional[List[Dict[str, Any]]] = None
    select: Optional[int] = None


@dataclass
class FileSource:
    """Reference to an existing file on disk or URL."""
    type: Literal["file"] = "file"
    path: str = ""
    start: Optional[float] = None
    end: Optional[float] = None


@dataclass
class SilenceSource:
    """Generates silence of a specified duration."""
    type: Literal["silence"] = "silence"
    duration: float = 0.0


@dataclass
class StillSource:
    """Creates a video clip from a static image held for a duration."""
    type: Literal["still"] = "still"
    image: Union[str, "Ref"] = ""
    duration: float = 0.0


# Union of all source types
Source = Union[ImageSource, VideoSource, TTSSource, FileSource, SilenceSource, StillSource]


# ---------------------------------------------------------------------------
# Ref and Generate types
# ---------------------------------------------------------------------------

@dataclass
class Ref:
    """Reference to another clip or asset's output."""
    ref: str = ""
    extract: Optional[str] = None  # "first_frame", "last_frame", "audio"


@dataclass
class Generate:
    """Inline generation instruction (embedded source)."""
    generate: Optional[Source] = None


# Union for first_frame / last_frame fields on VideoSource
FrameInput = Union[str, Ref, Generate, None]


# ---------------------------------------------------------------------------
# Core model
# ---------------------------------------------------------------------------

@dataclass
class Clip:
    """A piece of media with a position on the timeline."""
    id: str = ""
    source: Optional[Source] = None
    start_time: Optional[float] = None
    duration: Union[float, Literal["auto"], None] = "auto"
    fit_to: Optional[str] = None
    fit_method: str = "speed"
    buffer_ms: float = 0.0
    label: Optional[str] = None


@dataclass
class Track:
    """An ordered collection of clips of the same type."""
    id: str = ""
    type: str = ""  # "video", "narration", "audio"
    clips: List[Clip] = field(default_factory=list)
    volume: Optional[float] = None  # 0.0-1.0, only used for audio tracks


@dataclass
class Project:
    """Project metadata and global visual settings."""
    name: str = ""
    description: Optional[str] = None
    aspect_ratio: str = "16:9"
    resolution: str = "720p"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

@dataclass
class VideoDefaults:
    model: str = "veo-3.1-fast"
    duration: int = 6
    generate_audio: bool = True
    aspect_ratio: str = "16:9"
    resolution: str = "720p"


@dataclass
class ImageDefaults:
    model: str = "nano-banana-pro"
    aspect_ratio: str = "16:9"
    resolution: str = "2K"
    output_format: str = "png"
    reference_images: List[str] = field(default_factory=list)
    safety_filter_level: str = "block_only_high"


@dataclass
class TTSDefaults:
    voice: str = "Kore"
    model: str = "gemini-2.5-flash-tts"
    voice_prompt: Optional[str] = None


@dataclass
class Defaults:
    video: VideoDefaults = field(default_factory=VideoDefaults)
    image: ImageDefaults = field(default_factory=ImageDefaults)
    tts: TTSDefaults = field(default_factory=TTSDefaults)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass
class OutputVariants:
    """Which output variants to produce."""
    narration_only: bool = True
    narration_sfx: bool = True
    images_only: bool = False


@dataclass
class Output:
    format: str = "mp4"
    variants: OutputVariants = field(default_factory=OutputVariants)
    narration_volume: float = 1.0
    sfx_volume: float = 0.3
    audio_mix: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Timeline (top-level)
# ---------------------------------------------------------------------------

@dataclass
class Timeline:
    """Top-level timeline document."""
    version: int = 1
    project: Optional[Project] = None
    defaults: Defaults = field(default_factory=Defaults)
    assets: Dict[str, Source] = field(default_factory=dict)
    tracks: List[Track] = field(default_factory=list)
    output: Output = field(default_factory=Output)


# ---------------------------------------------------------------------------
# Result types (used by executor/adapters in later phases)
# ---------------------------------------------------------------------------

@dataclass
class NodeResult:
    """Result of generating or resolving a single node."""
    path: Path = field(default_factory=lambda: Path())
    duration: Optional[float] = None  # None for images
    media_type: str = ""  # "image" | "video" | "audio"


# ---------------------------------------------------------------------------
# Validation types
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    """A single validation finding."""
    path: str = ""       # JSON path like "tracks[0].clips[2].source.duration"
    message: str = ""
    severity: str = "error"  # "error" | "warning"


@dataclass
class ValidationResult:
    """Aggregated validation outcome."""
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict:
        return {
            "valid": self.is_valid,
            "errors": [{"severity": e.severity, "message": e.message, "path": e.path} for e in self.errors],
            "warnings": [{"severity": w.severity, "message": w.message, "path": w.path} for w in self.warnings],
        }


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    # Source types
    "ImageSource",
    "VideoSource",
    "TTSSource",
    "FileSource",
    "SilenceSource",
    "StillSource",
    "Source",
    # Ref / Generate
    "Ref",
    "Generate",
    "FrameInput",
    # Core model
    "Clip",
    "Track",
    "Project",
    # Defaults
    "VideoDefaults",
    "ImageDefaults",
    "TTSDefaults",
    "Defaults",
    # Output
    "OutputVariants",
    "Output",
    # Timeline
    "Timeline",
    # Result types
    "NodeResult",
    # Validation
    "ValidationError",
    "ValidationResult",
]
