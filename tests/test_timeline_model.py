"""Tests for the timeline data model."""

from pathlib import Path

import pytest

from timeline.model import (
    Clip,
    Defaults,
    FileSource,
    Generate,
    ImageDefaults,
    ImageSource,
    NodeResult,
    Output,
    Project,
    Ref,
    SilenceSource,
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


# ---------------------------------------------------------------------------
# Construction with defaults
# ---------------------------------------------------------------------------

class TestDefaultConstruction:
    def test_timeline_defaults(self):
        t = Timeline()
        assert t.version == 1
        assert t.project is None
        assert isinstance(t.defaults, Defaults)
        assert t.assets == {}
        assert t.tracks == []
        assert isinstance(t.output, Output)

    def test_project_defaults(self):
        p = Project()
        assert p.name == ""
        assert p.description is None
        assert p.aspect_ratio == "16:9"
        assert p.resolution == "720p"

    def test_clip_defaults(self):
        c = Clip()
        assert c.id == ""
        assert c.source is None
        assert c.start_time is None
        assert c.duration == "auto"
        assert c.fit_to is None
        assert c.fit_method == "speed"
        assert c.buffer_ms == 0.0
        assert c.label is None

    def test_track_defaults(self):
        t = Track()
        assert t.id == ""
        assert t.type == ""
        assert t.clips == []

    def test_output_defaults(self):
        o = Output()
        assert o.format == "mp4"
        assert o.audio_mix is None

    def test_defaults_defaults(self):
        d = Defaults()
        assert isinstance(d.video, VideoDefaults)
        assert isinstance(d.image, ImageDefaults)
        assert isinstance(d.tts, TTSDefaults)


# ---------------------------------------------------------------------------
# Source types — defaults and discriminator
# ---------------------------------------------------------------------------

class TestSourceTypes:
    def test_image_source_defaults(self):
        s = ImageSource()
        assert s.type == "image"
        assert s.prompt == ""
        assert s.reference_images == []
        assert s.model == "nano-banana-pro"
        assert s.aspect_ratio == "16:9"
        assert s.resolution == "2K"
        assert s.output_format == "png"
        assert s.safety_filter_level == "block_only_high"
        assert s.candidates is None
        assert s.select is None

    def test_video_source_defaults(self):
        s = VideoSource()
        assert s.type == "video"
        assert s.prompt == ""
        assert s.first_frame is None
        assert s.last_frame is None
        assert s.model == "seedance-2.0-fast"
        assert s.duration == 5
        assert s.generate_audio is True
        assert s.negative_prompt is None
        assert s.seed is None

    def test_tts_source_defaults(self):
        s = TTSSource()
        assert s.type == "tts"
        assert s.text == ""
        assert s.voice == "Kore"
        assert s.voice_prompt is None
        assert s.model == "gemini-2.5-flash-tts"

    def test_file_source_defaults(self):
        s = FileSource()
        assert s.type == "file"
        assert s.path == ""
        assert s.start is None
        assert s.end is None

    def test_silence_source_defaults(self):
        s = SilenceSource()
        assert s.type == "silence"
        assert s.duration == 0.0

    def test_still_source_defaults(self):
        s = StillSource()
        assert s.type == "still"
        assert s.image == ""
        assert s.duration == 0.0

    def test_source_type_discrimination(self):
        """Each source type has a unique type discriminator."""
        sources = [ImageSource(), VideoSource(), TTSSource(),
                   FileSource(), SilenceSource(), StillSource()]
        types = [s.type for s in sources]
        assert types == ["image", "video", "tts", "file", "silence", "still"]
        assert len(set(types)) == len(types), "type values must be unique"


# ---------------------------------------------------------------------------
# Construction with all fields
# ---------------------------------------------------------------------------

class TestFullConstruction:
    def test_image_source_all_fields(self):
        s = ImageSource(
            prompt="A green leaf",
            reference_images=["ref1.png", "ref2.png"],
            model="nano-banana-pro",
            aspect_ratio="9:16",
            resolution="4K",
            output_format="jpg",
            safety_filter_level="block_none",
            candidates=[{"prompt": "alt"}],
            select=0,
        )
        assert s.prompt == "A green leaf"
        assert s.reference_images == ["ref1.png", "ref2.png"]
        assert s.candidates == [{"prompt": "alt"}]
        assert s.select == 0

    def test_video_source_all_fields(self):
        ref = Ref(ref="img-1")
        s = VideoSource(
            prompt="A swaying leaf",
            first_frame=ref,
            last_frame="path/to/frame.png",
            model="seedance-2.0",
            duration=8,
            aspect_ratio="9:16",
            resolution="720p",
            generate_audio=False,
            negative_prompt="blurry",
            seed=42,
            candidates=[{"prompt": "alt"}],
            select=1,
        )
        assert s.first_frame is ref
        assert s.last_frame == "path/to/frame.png"
        assert s.seed == 42

    def test_tts_source_all_fields(self):
        s = TTSSource(
            text="Hello world",
            voice="Alnilam",
            voice_prompt="Calm tone",
            model="gemini-2.5-flash-tts",
            candidates=[{"text": "alt"}],
            select=0,
        )
        assert s.text == "Hello world"
        assert s.voice == "Alnilam"

    def test_clip_all_fields(self):
        c = Clip(
            id="vid-1",
            source=VideoSource(prompt="test"),
            start_time=5.0,
            duration=10.0,
            fit_to="narr-1",
            fit_method="trim",
            buffer_ms=200.0,
            label="Opening shot",
        )
        assert c.id == "vid-1"
        assert c.start_time == 5.0
        assert c.duration == 10.0
        assert c.fit_to == "narr-1"

    def test_timeline_all_fields(self):
        t = Timeline(
            version=1,
            project=Project(name="Test", description="A test project"),
            defaults=Defaults(),
            assets={"img-1": ImageSource(prompt="leaf")},
            tracks=[Track(id="video", type="video", clips=[
                Clip(id="v1", source=VideoSource(prompt="test")),
            ])],
            output=Output(format="mp4", audio_mix={"narration": 1.0}),
        )
        assert t.project.name == "Test"
        assert "img-1" in t.assets
        assert len(t.tracks) == 1
        assert t.tracks[0].clips[0].id == "v1"


# ---------------------------------------------------------------------------
# Ref and Generate
# ---------------------------------------------------------------------------

class TestRefAndGenerate:
    def test_ref_basic(self):
        r = Ref(ref="img-hook")
        assert r.ref == "img-hook"
        assert r.extract is None

    def test_ref_with_extract(self):
        r = Ref(ref="vid-1", extract="last_frame")
        assert r.extract == "last_frame"

    def test_generate_with_image_source(self):
        g = Generate(generate=ImageSource(prompt="a leaf"))
        assert isinstance(g.generate, ImageSource)
        assert g.generate.prompt == "a leaf"

    def test_generate_default(self):
        g = Generate()
        assert g.generate is None

    def test_video_source_with_generate_first_frame(self):
        gen = Generate(generate=ImageSource(prompt="opening frame"))
        v = VideoSource(prompt="scene", first_frame=gen)
        assert isinstance(v.first_frame, Generate)
        assert v.first_frame.generate.prompt == "opening frame"


# ---------------------------------------------------------------------------
# Defaults types
# ---------------------------------------------------------------------------

class TestDefaultsTypes:
    def test_video_defaults(self):
        d = VideoDefaults()
        assert d.model == "seedance-2.0-fast"
        assert d.duration == 5
        assert d.generate_audio is True

    def test_image_defaults(self):
        d = ImageDefaults()
        assert d.model == "nano-banana-pro"
        assert d.reference_images == []

    def test_tts_defaults(self):
        d = TTSDefaults()
        assert d.voice == "Kore"
        assert d.voice_prompt is None


# ---------------------------------------------------------------------------
# Validation types
# ---------------------------------------------------------------------------

class TestValidation:
    def test_validation_result_valid(self):
        vr = ValidationResult()
        assert vr.is_valid is True

    def test_validation_result_with_errors(self):
        vr = ValidationResult(errors=[
            ValidationError(path="version", message="missing", severity="error"),
        ])
        assert vr.is_valid is False

    def test_validation_result_warnings_only(self):
        vr = ValidationResult(warnings=[
            ValidationError(path="tracks[0]", message="empty", severity="warning"),
        ])
        assert vr.is_valid is True

    def test_validation_result_to_dict_valid(self):
        vr = ValidationResult()
        d = vr.to_dict()
        assert d["valid"] is True
        assert d["errors"] == []
        assert d["warnings"] == []

    def test_validation_result_to_dict_with_errors(self):
        vr = ValidationResult(
            errors=[ValidationError(path="p", message="bad", severity="error")],
            warnings=[ValidationError(path="w", message="warn", severity="warning")],
        )
        d = vr.to_dict()
        assert d["valid"] is False
        assert len(d["errors"]) == 1
        assert d["errors"][0] == {"severity": "error", "message": "bad", "path": "p"}
        assert len(d["warnings"]) == 1
        assert d["warnings"][0] == {"severity": "warning", "message": "warn", "path": "w"}

    def test_validation_error_fields(self):
        e = ValidationError(
            path="tracks[0].clips[1].source.duration",
            message="must be positive",
            severity="error",
        )
        assert e.path == "tracks[0].clips[1].source.duration"
        assert e.severity == "error"


# ---------------------------------------------------------------------------
# NodeResult
# ---------------------------------------------------------------------------

class TestNodeResult:
    def test_node_result_defaults(self):
        nr = NodeResult()
        assert nr.path == Path()
        assert nr.duration is None
        assert nr.media_type == ""

    def test_node_result_with_values(self):
        nr = NodeResult(
            path=Path("/tmp/output.mp4"),
            duration=6.5,
            media_type="video",
        )
        assert nr.path == Path("/tmp/output.mp4")
        assert nr.duration == 6.5
        assert nr.media_type == "video"


# ---------------------------------------------------------------------------
# List independence (mutable default fields)
# ---------------------------------------------------------------------------

class TestMutableDefaults:
    def test_track_clips_independence(self):
        """Each Track instance must have its own clips list."""
        t1 = Track()
        t2 = Track()
        t1.clips.append(Clip(id="a"))
        assert t2.clips == []

    def test_image_source_ref_images_independence(self):
        s1 = ImageSource()
        s2 = ImageSource()
        s1.reference_images.append("x.png")
        assert s2.reference_images == []

    def test_timeline_assets_independence(self):
        t1 = Timeline()
        t2 = Timeline()
        t1.assets["x"] = ImageSource()
        assert t2.assets == {}
