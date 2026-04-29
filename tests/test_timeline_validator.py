"""Tests for timeline validator — one test per REQ-SVAL/REQ-DEPV rule."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from timeline.model import (
    Clip,
    FileSource,
    Generate,
    ImageSource,
    Project,
    Ref,
    SilenceSource,
    StillSource,
    TTSSource,
    Timeline,
    Track,
    ValidationError,
    ValidationResult,
    VideoSource,
)
from timeline.validator import validate


def _make_timeline(**kwargs):
    """Build a minimal valid timeline, overriding with kwargs."""
    defaults = dict(
        version=1,
        project=Project(name="test"),
        tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=VideoSource(prompt="test video")),
        ])],
    )
    defaults.update(kwargs)
    return Timeline(**defaults)


def _valid_timeline():
    return _make_timeline()


class TestStaticValidation:
    """Pass 1 — REQ-SVAL rules."""

    # REQ-SVAL-002: Required fields — project.name
    def test_missing_project(self):
        tl = _make_timeline(project=None)
        result = validate(tl)
        assert not result.is_valid
        assert any("project is required" in e.message for e in result.errors)

    def test_missing_project_name(self):
        tl = _make_timeline(project=Project(name=""))
        result = validate(tl)
        assert not result.is_valid
        assert any("project.name" in e.path for e in result.errors)

    # REQ-SVAL-003: ID uniqueness
    def test_duplicate_clip_id(self):
        tl = _make_timeline(tracks=[
            Track(id="t1", type="video", clips=[
                Clip(id="dup", source=VideoSource(prompt="a")),
            ]),
            Track(id="t2", type="audio", clips=[
                Clip(id="dup", source=TTSSource(text="hello")),
            ]),
        ])
        result = validate(tl)
        assert not result.is_valid
        dup_errors = [e for e in result.errors if "Duplicate ID" in e.message]
        assert len(dup_errors) >= 1
        assert "dup" in dup_errors[0].message

    def test_duplicate_clip_and_asset_id(self):
        tl = _make_timeline(
            assets={"shared": ImageSource(prompt="asset")},
            tracks=[Track(id="t1", type="video", clips=[
                Clip(id="shared", source=VideoSource(prompt="clip")),
            ])],
        )
        result = validate(tl)
        assert not result.is_valid

    # REQ-SVAL-004: ID format
    def test_invalid_id_format(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="bad id!", source=VideoSource(prompt="test")),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("Invalid ID format" in e.message for e in result.errors)

    def test_valid_id_format(self):
        tl = _make_timeline(tracks=[Track(id="track-1", type="video", clips=[
            Clip(id="clip_1-a", source=VideoSource(prompt="test")),
        ])])
        result = validate(tl)
        assert result.is_valid

    # REQ-SVAL-005: Track type values
    def test_invalid_track_type(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="music", clips=[
            Clip(id="c1", source=VideoSource(prompt="test")),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("Invalid track type" in e.message for e in result.errors)

    # REQ-SVAL-006: Source type values (tested implicitly via type discriminator)
    # Since we use dataclasses with literal types, an invalid source type
    # would be caught at parse time. We test that the validator also checks.

    # REQ-SVAL-018: Video model name validation
    def test_invalid_video_model(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=VideoSource(prompt="test", model="veo-3.1-lite")),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("Invalid video model" in e.message for e in result.errors)

    # REQ-SVAL-012: Voice name validation
    def test_unknown_voice_with_suggestion(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="narration", clips=[
            Clip(id="c1", source=TTSSource(text="hello", voice="Koree")),
        ])])
        result = validate(tl)
        assert not result.is_valid
        voice_error = [e for e in result.errors if "voice" in e.path.lower()]
        assert len(voice_error) >= 1
        assert "Kore" in voice_error[0].message  # Should suggest Kore

    def test_known_voice_passes(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="narration", clips=[
            Clip(id="c1", source=TTSSource(text="hello", voice="Kore")),
        ])])
        result = validate(tl)
        assert result.is_valid

    # REQ-SVAL-013: File path existence
    def test_file_not_found(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmpdir:
            tl = _make_timeline(tracks=[Track(id="t1", type="audio", clips=[
                Clip(id="c1", source=FileSource(path="nonexistent.mp3")),
            ])])
            result = validate(tl, timeline_dir=Path(tmpdir))
            assert not result.is_valid
            assert any("File not found" in e.message for e in result.errors)

    def test_file_exists(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmpdir:
            # Create the file
            Path(tmpdir, "audio.mp3").touch()
            tl = _make_timeline(tracks=[Track(id="t1", type="audio", clips=[
                Clip(id="c1", source=FileSource(path="audio.mp3")),
            ])])
            result = validate(tl, timeline_dir=Path(tmpdir))
            assert result.is_valid

    # REQ-SVAL-014: Reference image existence
    def test_reference_image_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
                Clip(id="c1", source=ImageSource(
                    prompt="test", reference_images=["missing.png"],
                )),
            ])])
            result = validate(tl, timeline_dir=Path(tmpdir))
            assert not result.is_valid

    def test_reference_image_url_passes(self):
        """HTTP URLs are not checked for file existence."""
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=ImageSource(
                prompt="test",
                reference_images=["https://example.com/img.png"],
            )),
        ])])
        result = validate(tl)
        assert result.is_valid

    # REQ-SVAL-015: Silence minimum duration
    def test_silence_below_minimum(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="audio", clips=[
            Clip(id="c1", source=SilenceSource(duration=0.05)),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("0.1" in e.message for e in result.errors)

    def test_silence_at_minimum(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="audio", clips=[
            Clip(id="c1", source=SilenceSource(duration=0.1)),
        ])])
        result = validate(tl)
        assert result.is_valid

    # REQ-SVAL-016: Candidates non-empty
    def test_empty_candidates(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=ImageSource(prompt="test", candidates=[])),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("candidates" in e.message for e in result.errors)

    # REQ-SVAL-017: Select bounds
    def test_select_out_of_bounds(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=ImageSource(
                prompt="test",
                candidates=[{"prompt": "alt"}],
                select=5,
            )),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("select" in e.message.lower() for e in result.errors)

    def test_select_valid(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=ImageSource(
                prompt="test",
                candidates=[{"prompt": "a"}, {"prompt": "b"}],
                select=2,
            )),
        ])])
        result = validate(tl)
        assert result.is_valid

    # REQ-SVAL-019: Image output_format
    def test_invalid_output_format(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=ImageSource(prompt="test", output_format="webp")),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("output_format" in e.message for e in result.errors)

    # REQ-SVAL-020: At least one track
    def test_no_tracks(self):
        tl = _make_timeline(tracks=[])
        result = validate(tl)
        assert not result.is_valid
        assert any("at least one track" in e.message.lower() for e in result.errors)

    def test_empty_clips_in_track(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[])])
        result = validate(tl)
        assert not result.is_valid
        assert any("at least one clip" in e.message.lower() for e in result.errors)

    # REQ-SVAL-002: Required source fields
    def test_missing_prompt_image(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=ImageSource(prompt="")),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("prompt" in e.message for e in result.errors)

    def test_missing_prompt_video(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=VideoSource(prompt="")),
        ])])
        result = validate(tl)
        assert not result.is_valid

    def test_missing_text_tts(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="narration", clips=[
            Clip(id="c1", source=TTSSource(text="")),
        ])])
        result = validate(tl)
        assert not result.is_valid

    def test_missing_path_file(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="audio", clips=[
            Clip(id="c1", source=FileSource(path="")),
        ])])
        result = validate(tl)
        assert not result.is_valid

    def test_missing_image_still(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=StillSource(image="", duration=3.0)),
        ])])
        result = validate(tl)
        assert not result.is_valid

    def test_missing_duration_still(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "img.png").touch()
            tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
                Clip(id="c1", source=StillSource(image="img.png", duration=0.0)),
            ])])
            result = validate(tl, timeline_dir=Path(tmpdir))
            assert not result.is_valid

    def test_missing_clip_id(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="", source=VideoSource(prompt="test")),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("clip.id" in e.message for e in result.errors)

    def test_missing_clip_source(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=None),
        ])])
        result = validate(tl)
        assert not result.is_valid

    # REQ-SVAL-018: Video model name validation
    def test_invalid_video_model(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=VideoSource(prompt="test", model="invalid-model")),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("Invalid video model" in e.message for e in result.errors)


class TestInputBounds:
    """Input size limit tests."""

    def test_too_many_tracks(self):
        tracks = [
            Track(id=f"t{i}", type="video", clips=[
                Clip(id=f"c{i}", source=VideoSource(prompt="test")),
            ])
            for i in range(51)
        ]
        tl = _make_timeline(tracks=tracks)
        result = validate(tl)
        assert not result.is_valid
        assert any("Too many tracks" in e.message for e in result.errors)

    def test_max_total_clips_pass(self):
        """500 clips should pass."""
        clips = [Clip(id=f"c{i}", source=VideoSource(prompt="test")) for i in range(500)]
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=clips[:200]),
                                     Track(id="t2", type="video", clips=clips[200:400]),
                                     Track(id="t3", type="video", clips=clips[400:])])
        result = validate(tl)
        assert result.is_valid

    def test_max_total_clips_exceeded(self):
        """501 clips should fail."""
        clips = [Clip(id=f"c{i}", source=VideoSource(prompt="test")) for i in range(501)]
        # Split across multiple tracks to stay under per-track limit
        tl = _make_timeline(tracks=[
            Track(id="t1", type="video", clips=clips[:200]),
            Track(id="t2", type="video", clips=clips[200:400]),
            Track(id="t3", type="video", clips=clips[400:]),
        ])
        result = validate(tl)
        assert not result.is_valid
        assert any("Too many total clips" in e.message for e in result.errors)

    def test_too_many_candidates(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=ImageSource(
                prompt="test",
                candidates=[{"prompt": f"c{i}"} for i in range(21)],
            )),
        ])])
        result = validate(tl)
        assert not result.is_valid

    def test_prompt_too_large(self):
        big_prompt = "x" * (10 * 1024 + 1)
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=VideoSource(prompt=big_prompt)),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("maximum size" in e.message for e in result.errors)


class TestSecurityChecks:
    """Security validation tests."""

    def test_ssrf_url_blocked(self):
        """Internal URLs should be blocked."""
        tl = _make_timeline(tracks=[Track(id="t1", type="audio", clips=[
            Clip(id="c1", source=FileSource(path="http://metadata.google.internal/secret")),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("Security error" in e.message for e in result.errors)

    def test_path_traversal_blocked(self):
        """Path traversal attempts should be blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tl = _make_timeline(tracks=[Track(id="t1", type="audio", clips=[
                Clip(id="c1", source=FileSource(path="../../../etc/passwd")),
            ])])
            result = validate(tl, timeline_dir=Path(tmpdir))
            assert not result.is_valid
            assert any("Security error" in e.message for e in result.errors)

    def test_reference_image_ssrf(self):
        """SSRF in reference_images is caught."""
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=ImageSource(
                prompt="test",
                reference_images=["http://169.254.169.254/metadata"],
            )),
        ])])
        result = validate(tl)
        assert not result.is_valid


class TestDependencyValidation:
    """Pass 2 — REQ-DEPV rules."""

    # REQ-DEPV-003: Ref target existence
    def test_ref_to_nonexistent_id(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=VideoSource(
                prompt="test", first_frame=Ref(ref="doesnt_exist"),
            )),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("does not exist" in e.message for e in result.errors)

    # REQ-DEPV-002: Cycle detection
    def test_cycle_in_dag(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="a", source=VideoSource(
                prompt="test", first_frame=Ref(ref="b"),
            )),
            Clip(id="b", source=VideoSource(
                prompt="test", first_frame=Ref(ref="a"),
            )),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("cycle" in e.message.lower() for e in result.errors)

    # REQ-DEPV-004/005: Type compatibility
    def test_first_frame_ref_to_audio_clip(self):
        """first_frame ref to a TTS clip (audio only) should error."""
        tl = _make_timeline(tracks=[
            Track(id="t1", type="narration", clips=[
                Clip(id="narr1", source=TTSSource(text="hello")),
            ]),
            Track(id="t2", type="video", clips=[
                Clip(id="vid1", source=VideoSource(
                    prompt="test", first_frame=Ref(ref="narr1"),
                )),
            ]),
        ])
        result = validate(tl)
        assert not result.is_valid
        assert any("does not produce image or video" in e.message for e in result.errors)

    def test_extract_audio_from_non_video(self):
        """extract: 'audio' on a non-video target should error."""
        tl = _make_timeline(
            assets={"img1": ImageSource(prompt="test")},
            tracks=[Track(id="t1", type="video", clips=[
                Clip(id="vid1", source=VideoSource(
                    prompt="test",
                    first_frame=Ref(ref="img1", extract="audio"),
                )),
            ])],
        )
        result = validate(tl)
        assert not result.is_valid
        assert any("requires a video source" in e.message for e in result.errors)

    # REQ-DEPV-006: fit_to target existence
    def test_fit_to_nonexistent(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=VideoSource(prompt="test"), fit_to="ghost"),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("fit_to target" in e.message for e in result.errors)

    # REQ-DEPV-007: fit_to timing cycle
    def test_fit_to_timing_cycle(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="a", source=VideoSource(prompt="test"), fit_to="b"),
            Clip(id="b", source=VideoSource(prompt="test"), fit_to="a"),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("Timing cycle" in e.message for e in result.errors)

    # REQ-DEPV-010: Deep chain warning (last_frame)
    def test_deep_first_frame_chain_warning(self):
        """Chain of >10 first_frame refs should produce warning."""
        clips = []
        for i in range(12):
            ff = Ref(ref=f"v{i-1}", extract="first_frame") if i > 0 else None
            clips.append(Clip(id=f"v{i}", source=VideoSource(
                prompt="test", first_frame=ff,
            )))
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=clips)])
        result = validate(tl)
        assert any("exceeds 10" in w.message for w in result.warnings)

    def test_deep_last_frame_chain_warning(self):
        """Chain of >10 last_frame refs should produce warning."""
        clips = []
        for i in range(12):
            lf = Ref(ref=f"v{i-1}", extract="last_frame") if i > 0 else None
            clips.append(Clip(id=f"v{i}", source=VideoSource(
                prompt="test", last_frame=lf,
            )))
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=clips)])
        result = validate(tl)
        assert any("exceeds 10" in w.message for w in result.warnings)

    # REQ-DEPV-008: Extract values
    def test_invalid_extract_value(self):
        tl = _make_timeline(
            assets={"vid1": VideoSource(prompt="test")},
            tracks=[Track(id="t1", type="video", clips=[
                Clip(id="c1", source=VideoSource(
                    prompt="test",
                    first_frame=Ref(ref="vid1", extract="middle_frame"),
                )),
            ])],
        )
        result = validate(tl)
        assert not result.is_valid
        assert any("Invalid extract value" in e.message for e in result.errors)

    # REQ-DEPV-009: Inline generate validation
    def test_inline_generate_missing_prompt(self):
        tl = _make_timeline(tracks=[Track(id="t1", type="video", clips=[
            Clip(id="c1", source=VideoSource(
                prompt="test",
                first_frame=Generate(generate=ImageSource(prompt="")),
            )),
        ])])
        result = validate(tl)
        assert not result.is_valid
        assert any("prompt" in e.message for e in result.errors)


class TestValidTimeline:
    """Sanity check: valid timelines pass validation."""

    def test_minimal_valid(self):
        result = validate(_valid_timeline())
        assert result.is_valid
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_valid_with_assets_and_refs(self):
        tl = _make_timeline(
            assets={"bg": ImageSource(prompt="background")},
            tracks=[Track(id="t1", type="video", clips=[
                Clip(id="vid1", source=VideoSource(
                    prompt="test", first_frame=Ref(ref="bg"),
                )),
            ])],
        )
        result = validate(tl)
        assert result.is_valid

    def test_valid_multi_track(self):
        tl = _make_timeline(tracks=[
            Track(id="t1", type="video", clips=[
                Clip(id="v1", source=VideoSource(prompt="visual")),
            ]),
            Track(id="t2", type="narration", clips=[
                Clip(id="n1", source=TTSSource(text="narration text")),
            ]),
            Track(id="t3", type="audio", clips=[
                Clip(id="s1", source=SilenceSource(duration=1.0)),
            ]),
        ])
        result = validate(tl)
        assert result.is_valid
