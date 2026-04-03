"""Tests for timeline DAG executor and resolver."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import os

import pytest

import generation.batch_img as batch_img
import generation.batch_vid as batch_vid
from shared.replicate_client import set_mock_mode
from timeline.model import (
    Clip,
    Defaults,
    FileSource,
    Generate,
    ImageDefaults,
    ImageSource,
    NodeResult,
    Project,
    Ref,
    SilenceSource,
    StillSource,
    TTSDefaults,
    TTSSource,
    Timeline,
    Track,
    VideoDefaults,
    VideoSource,
)
from timeline.executor import RunResult, execute_timeline
from timeline.resolver import resolve_frame_input, resolve_ref


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_timeline(**kwargs) -> Timeline:
    """Build a Timeline with sensible defaults, overriding with kwargs."""
    return Timeline(
        version=1,
        project=kwargs.get("project", Project(name="test")),
        defaults=kwargs.get("defaults", Defaults()),
        assets=kwargs.get("assets", {}),
        tracks=kwargs.get("tracks", []),
    )


@pytest.fixture(autouse=True)
def _ensure_api_keys(monkeypatch):
    """Set dummy API keys so mock mode doesn't fail on missing tokens."""
    if not os.environ.get("GOOGLE_API_KEY"):
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key-for-mock")
    if not os.environ.get("REPLICATE_API_TOKEN"):
        monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token-for-mock")


# ---------------------------------------------------------------------------
# Executor tests — validation gate (MAJOR-3)
# ---------------------------------------------------------------------------


class TestExecuteValidation:
    def test_rejects_invalid_timeline(self, tmp_path):
        """execute_timeline raises ValueError for an invalid timeline."""
        # Timeline with no tracks and no project — fails validation
        tl = Timeline(version=1, tracks=[], assets={})
        with pytest.raises(ValueError, match="Timeline validation failed"):
            execute_timeline(tl, tmp_path, stage="final", mock=True)

    def test_rejects_missing_clip_source(self, tmp_path):
        """execute_timeline rejects clips without a source."""
        tl = Timeline(
            version=1,
            project=Project(name="test"),
            tracks=[Track(id="v", type="video", clips=[
                Clip(id="c1", source=None),
            ])],
            assets={},
        )
        with pytest.raises(ValueError, match="Timeline validation failed"):
            execute_timeline(tl, tmp_path, stage="final", mock=True)


# ---------------------------------------------------------------------------
# Executor tests
# ---------------------------------------------------------------------------

class TestExecuteSimpleTimeline:
    def test_single_image_clip(self, tmp_path):
        """Parse a minimal timeline with one image clip, execute in mock mode,
        verify NodeResult exists with correct path."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(id="img1", source=ImageSource(prompt="a cat")),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="final", mock=True)

        assert isinstance(result, RunResult)
        assert result.success is True
        assert "img1" in result.results
        assert result.results["img1"].media_type == "image"
        assert result.results["img1"].path.exists()


class TestExecuteMultiType:
    def test_image_tts_silence(self, tmp_path):
        """Timeline with image + TTS + silence clips (all level 0) —
        verify all results present."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(id="img1", source=ImageSource(prompt="mountains")),
                ]),
                Track(id="narration", type="narration", clips=[
                    Clip(id="tts1", source=TTSSource(text="Hello world")),
                ]),
                Track(id="audio", type="audio", clips=[
                    Clip(id="sil1", source=SilenceSource(duration=2.0)),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="final", mock=True)

        assert result.success is True
        assert "img1" in result.results
        assert "tts1" in result.results
        assert "sil1" in result.results
        assert result.results["img1"].media_type == "image"
        assert result.results["tts1"].media_type == "audio"
        assert result.results["sil1"].media_type == "audio"


class TestExecuteDAGOrdering:
    def test_image_then_video_ref(self, tmp_path):
        """Image asset + video clip that refs the image via first_frame —
        verify image generates before video (video has result)."""
        tl = _make_timeline(
            assets={
                "hero_img": ImageSource(prompt="a hero image"),
            },
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(
                        id="vid1",
                        source=VideoSource(
                            prompt="zoom into hero",
                            first_frame=Ref(ref="hero_img"),
                        ),
                    ),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="final", mock=True)

        assert result.success is True
        assert "hero_img" in result.results
        assert "vid1" in result.results
        assert result.results["hero_img"].media_type == "image"
        assert result.results["vid1"].media_type == "video"


class TestExecuteStageImages:
    def test_stage_images_excludes_video(self, tmp_path):
        """stage='images' — only image/audio results, no video."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(id="img1", source=ImageSource(prompt="test")),
                    Clip(id="vid1", source=VideoSource(prompt="test video")),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="images", mock=True)

        assert result.success is True
        assert "img1" in result.results
        assert "vid1" not in result.results


class TestExecuteStageVideos:
    def test_stage_videos_includes_all(self, tmp_path):
        """stage='videos' — all results including video."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(id="img1", source=ImageSource(prompt="test")),
                    Clip(id="vid1", source=VideoSource(prompt="test video")),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="videos", mock=True)

        assert result.success is True
        assert "img1" in result.results
        assert "vid1" in result.results


class TestExecuteEmptyTimeline:
    def test_empty_tracks_rejected_by_validation(self, tmp_path):
        """Empty tracks are rejected by validation (MAJOR-3)."""
        tl = _make_timeline(tracks=[])

        with pytest.raises(ValueError, match="Timeline validation failed"):
            execute_timeline(tl, tmp_path, stage="final", mock=True)


class TestExecuteFailedNodeSkipsDependents:
    def test_failed_image_skips_video(self, tmp_path):
        """Mock a failing image — video that refs it should be skipped."""
        tl = _make_timeline(
            assets={
                "bad_img": ImageSource(prompt="will fail"),
            },
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(
                        id="vid1",
                        source=VideoSource(
                            prompt="depends on bad image",
                            first_frame=Ref(ref="bad_img"),
                        ),
                    ),
                ]),
            ],
        )

        # Patch image generation to raise an exception
        with patch(
            "timeline.image_gen.generate_images",
            side_effect=RuntimeError("mock image failure"),
        ):
            result = execute_timeline(tl, tmp_path, stage="final", mock=True)

        assert result.success is False
        assert "bad_img" not in result.results
        assert "vid1" not in result.results
        assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# Resolver tests
# ---------------------------------------------------------------------------

class TestResolverBasicRef:
    def test_resolve_ref_basic(self):
        """resolve_ref with a completed NodeResult returns the result path."""
        results = {
            "img1": NodeResult(path=Path("/tmp/images/img1.png"), media_type="image"),
        }
        ref = Ref(ref="img1")
        path = resolve_ref(ref, results, Path("/tmp/run"))
        assert path == Path("/tmp/images/img1.png")

    def test_resolve_ref_missing_raises(self):
        """resolve_ref raises KeyError for missing ref."""
        results = {}
        ref = Ref(ref="nonexistent")
        with pytest.raises(KeyError):
            resolve_ref(ref, results, Path("/tmp/run"))


class TestResolverExtractFirstFrame:
    def test_extract_first_frame(self, tmp_path):
        """resolve_ref with extract='first_frame' calls extract and returns path."""
        video_path = tmp_path / "vid.mp4"
        video_path.touch()

        results = {
            "vid1": NodeResult(path=video_path, duration=5.0, media_type="video"),
        }
        ref = Ref(ref="vid1", extract="first_frame")

        extracted = tmp_path / "extracted_frames" / "vid1_first_frame.png"

        with patch("shared.media.extract_first_frame", return_value=extracted) as mock_fn:
            path = resolve_ref(ref, results, tmp_path)
            mock_fn.assert_called_once_with(video_path, extracted)
            assert path == extracted


class TestResolverFrameInputString:
    def test_string_path(self):
        """resolve_frame_input with a string returns Path directly."""
        path = resolve_frame_input("/some/image.png", {}, Path("/tmp"))
        assert path == Path("/some/image.png")

    def test_none_returns_none(self):
        """resolve_frame_input with None returns None."""
        path = resolve_frame_input(None, {}, Path("/tmp"))
        assert path is None

    def test_ref_delegates_to_resolve_ref(self):
        """resolve_frame_input with a Ref delegates to resolve_ref."""
        results = {
            "img1": NodeResult(path=Path("/tmp/img1.png"), media_type="image"),
        }
        ref = Ref(ref="img1")
        path = resolve_frame_input(ref, results, Path("/tmp"))
        assert path == Path("/tmp/img1.png")

    def test_generate_returns_none(self):
        """resolve_frame_input with a Generate returns None (executor handles)."""
        gen = Generate(generate=ImageSource(prompt="inline"))
        path = resolve_frame_input(gen, {}, Path("/tmp"))
        assert path is None


# ---------------------------------------------------------------------------
# Timing + Fitting integration tests
# ---------------------------------------------------------------------------


class TestTimingFittingPass:
    def test_layout_populated_after_execution(self, tmp_path):
        """run_result.layout is populated when stage is 'videos' or 'final'."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(id="vid1", source=VideoSource(prompt="test video")),
                ]),
                Track(id="narration", type="narration", clips=[
                    Clip(id="tts1", source=TTSSource(text="Hello world")),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="final", mock=True)

        assert result.success is True
        assert result.layout is not None
        assert "vid1" in result.layout.clips
        assert "tts1" in result.layout.clips

    def test_layout_none_for_images_stage(self, tmp_path):
        """run_result.layout is None when stage is 'images'."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(id="img1", source=ImageSource(prompt="test")),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="images", mock=True)

        assert result.success is True
        assert result.layout is None

    def test_clip_without_fit_not_adjusted(self, tmp_path):
        """Clips without fit_to should not have needs_fit set."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(id="vid1", source=VideoSource(prompt="test video")),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="videos", mock=True)

        assert result.success is True
        assert result.layout is not None
        assert result.layout.clips["vid1"].needs_fit is False

    def test_fit_to_sets_needs_fit(self, tmp_path):
        """Clips with fit_to targeting a clip with different duration have needs_fit=True."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(id="vid1", source=VideoSource(prompt="test video")),
                ]),
                Track(id="narration", type="narration", clips=[
                    Clip(
                        id="tts1",
                        source=TTSSource(text="Hello world"),
                        fit_to="vid1",
                    ),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="final", mock=True)

        assert result.success is True
        assert result.layout is not None
        # tts1 has fit_to="vid1", so it should have needs_fit if durations differ
        tts_layout = result.layout.clips["tts1"]
        assert tts_layout.fit_to == "vid1"
        # final_duration should match vid1's duration
        vid_layout = result.layout.clips["vid1"]
        assert tts_layout.final_duration == vid_layout.final_duration

    def test_fit_adjustment_updates_result(self, tmp_path):
        """When fit adjustment runs, the result path/duration should be updated."""
        tl = _make_timeline(
            tracks=[
                Track(id="narration", type="narration", clips=[
                    Clip(id="tts1", source=TTSSource(text="Short")),
                ]),
                Track(id="video", type="video", clips=[
                    Clip(
                        id="vid1",
                        source=VideoSource(prompt="a video"),
                        fit_to="tts1",
                    ),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="final", mock=True)

        assert result.success is True
        assert result.layout is not None
        vid_layout = result.layout.clips["vid1"]
        # If fit was needed, the result duration should match the layout
        if vid_layout.needs_fit:
            assert result.results["vid1"].duration == vid_layout.final_duration


# ---------------------------------------------------------------------------
# Assembly pass tests
# ---------------------------------------------------------------------------


class TestAssemblyPass:
    def _make_simple_timeline(self):
        """Build a timeline with image + TTS clips for assembly tests."""
        return _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(id="img1", source=ImageSource(prompt="test")),
                ]),
                Track(id="narration", type="narration", clips=[
                    Clip(id="tts1", source=TTSSource(text="Hello")),
                ]),
            ],
        )

    def test_assembly_called_for_final_stage(self, tmp_path):
        """assemble_timeline is called when stage='final'."""
        tl = self._make_simple_timeline()

        with patch("timeline.executor.assemble_timeline", return_value={}) as mock_asm:
            result = execute_timeline(tl, tmp_path, stage="final", mock=True)

        assert result.success is True
        mock_asm.assert_called_once()

    def test_assembly_not_called_for_videos_stage(self, tmp_path):
        """assemble_timeline is NOT called when stage='videos'."""
        tl = self._make_simple_timeline()

        with patch("timeline.executor.assemble_timeline") as mock_asm:
            result = execute_timeline(tl, tmp_path, stage="videos", mock=True)

        assert result.success is True
        mock_asm.assert_not_called()

    def test_assembly_not_called_for_images_stage(self, tmp_path):
        """assemble_timeline is NOT called when stage='images'."""
        tl = self._make_simple_timeline()

        with patch("timeline.executor.assemble_timeline") as mock_asm:
            result = execute_timeline(tl, tmp_path, stage="images", mock=True)

        assert result.success is True
        mock_asm.assert_not_called()

    def test_assembly_failure_recorded_as_error(self, tmp_path):
        """When assemble_timeline raises, the error is recorded."""
        tl = self._make_simple_timeline()

        with patch(
            "timeline.executor.assemble_timeline",
            side_effect=RuntimeError("ffmpeg exploded"),
        ):
            result = execute_timeline(tl, tmp_path, stage="final", mock=True)

        assert any("Assembly failed" in e for e in result.errors)

    def test_assembly_outputs_in_run_result(self, tmp_path):
        """RunResult.outputs is populated from assemble_timeline return value."""
        tl = self._make_simple_timeline()
        fake_outputs = {
            "narration_only": Path("/tmp/final.mp4"),
            "narration_sfx": Path("/tmp/final_sfx.mp4"),
        }

        with patch(
            "timeline.executor.assemble_timeline",
            return_value=fake_outputs,
        ):
            result = execute_timeline(tl, tmp_path, stage="final", mock=True)

        assert result.outputs == fake_outputs
