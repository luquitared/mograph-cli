"""Tests for timeline/video_gen.py — video generation adapter."""

import asyncio
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from generation import batch_vid
from shared.media import extract_audio_track, extract_first_frame
from timeline.model import NodeResult, VideoDefaults, VideoSource
from timeline.video_gen import (
    MODEL_KIND_MAP,
    VideoJob,
    _build_job_dict,
    _get_model_owner_name,
    generate_videos,
)


# ---------------------------------------------------------------------------
# Model kind mapping
# ---------------------------------------------------------------------------

class TestModelKindMapping:
    def test_veo_quality(self):
        assert MODEL_KIND_MAP["veo-3.1"] == "quality"

    def test_veo_fast(self):
        assert MODEL_KIND_MAP["veo-3.1-fast"] == "fast"

    def test_veo_lite(self):
        assert MODEL_KIND_MAP["veo-3.1-lite"] == "lite"

    def test_kling(self):
        assert MODEL_KIND_MAP["kling-v3"] == "kling"

    def test_get_model_owner_name_quality(self):
        owner, name = _get_model_owner_name("veo-3.1")
        assert owner == "google"
        assert name == "veo-3.1"

    def test_get_model_owner_name_fast(self):
        owner, name = _get_model_owner_name("veo-3.1-fast")
        assert owner == "google"
        assert name == "veo-3.1-fast"

    def test_get_model_owner_name_lite(self):
        owner, name = _get_model_owner_name("veo-3.1-lite")
        assert owner == "google"
        assert name == "veo-3.1-lite"

    def test_get_model_owner_name_kling(self):
        owner, name = _get_model_owner_name("kling-v3")
        assert owner == "kwaivgi"
        assert name == "kling-v3-omni-video"

    def test_get_model_owner_name_unknown_falls_back(self):
        owner, name = _get_model_owner_name("unknown-model")
        # Falls back to fast
        assert owner == "google"
        assert name == "veo-3.1-fast"


# ---------------------------------------------------------------------------
# Job dict construction
# ---------------------------------------------------------------------------

class TestBuildJobDict:
    def test_basic_job(self):
        source = VideoSource(prompt="a cat walking", duration=8, aspect_ratio="16:9")
        job = VideoJob(clip_id="v1", source=source)
        defaults = VideoDefaults()

        result = _build_job_dict(job, defaults)

        assert result["prompt"] == "a cat walking"
        assert result["first_frame_image"] is None
        assert result["last_frame_image"] is None
        assert result["config"]["duration"] == 8
        assert result["config"]["aspect_ratio"] == "16:9"

    def test_with_frame_paths(self):
        source = VideoSource(prompt="transition")
        job = VideoJob(
            clip_id="v2",
            source=source,
            first_frame_path=Path("/tmp/first.png"),
            last_frame_path=Path("/tmp/last.png"),
        )
        defaults = VideoDefaults()

        result = _build_job_dict(job, defaults)

        assert result["first_frame_image"] == "/tmp/first.png"
        assert result["last_frame_image"] == "/tmp/last.png"

    def test_all_fields(self):
        source = VideoSource(
            prompt="cinematic shot",
            duration=6,
            aspect_ratio="9:16",
            resolution="1080p",
            generate_audio=False,
            negative_prompt="blurry",
            seed=42,
        )
        job = VideoJob(clip_id="v3", source=source)
        defaults = VideoDefaults()

        result = _build_job_dict(job, defaults)

        assert result["config"]["duration"] == 6
        assert result["config"]["aspect_ratio"] == "9:16"
        assert result["config"]["resolution"] == "1080p"
        assert result["config"]["generate_audio"] is False
        assert result["config"]["negative_prompt"] == "blurry"
        assert result["config"]["seed"] == 42

    def test_defaults_applied(self):
        source = VideoSource(prompt="test")
        job = VideoJob(clip_id="v4", source=source)
        defaults = VideoDefaults(
            duration=8,
            aspect_ratio="9:16",
            resolution="1080p",
            generate_audio=False,
        )

        result = _build_job_dict(job, defaults)

        # Source has defaults (duration=6, aspect_ratio="16:9" etc),
        # so they won't fall through to VideoDefaults
        assert result["config"]["duration"] == 6  # source default
        assert result["config"]["aspect_ratio"] == "16:9"  # source default


# ---------------------------------------------------------------------------
# Mock mode integration
# ---------------------------------------------------------------------------

class TestGenerateVideosMock:
    @pytest.mark.asyncio
    async def test_mock_generates_videos(self, tmp_path):
        """With MOCK_REPLICATE=True, process_job returns a mock video file."""
        original_mock = batch_vid.MOCK_REPLICATE
        batch_vid.MOCK_REPLICATE = True
        try:
            source = VideoSource(prompt="test video", model="veo-3.1-fast")
            jobs = [VideoJob(clip_id="clip_001", source=source)]
            defaults = VideoDefaults()

            with patch.dict("os.environ", {"REPLICATE_API_TOKEN": "test-token"}):
                results = await generate_videos(
                    jobs=jobs,
                    run_dir=tmp_path,
                    defaults=defaults,
                    concurrency=1,
                    poll_sec=0.1,
                )

            assert "clip_001" in results
            result = results["clip_001"]
            assert result.media_type == "video"
            assert result.path.exists()
            assert result.duration is not None
            assert result.duration > 0
        finally:
            batch_vid.MOCK_REPLICATE = original_mock

    @pytest.mark.asyncio
    async def test_empty_jobs_returns_empty(self, tmp_path):
        results = await generate_videos(
            jobs=[],
            run_dir=tmp_path,
            defaults=VideoDefaults(),
        )
        assert results == {}

    @pytest.mark.asyncio
    async def test_failed_job_does_not_crash_batch(self, tmp_path):
        """One failed job should not prevent other jobs from completing."""
        original_mock = batch_vid.MOCK_REPLICATE
        batch_vid.MOCK_REPLICATE = True
        try:
            good_source = VideoSource(prompt="good video", model="veo-3.1-fast")
            bad_source = VideoSource(prompt="", model="veo-3.1-fast")  # Empty prompt → error

            jobs = [
                VideoJob(clip_id="good", source=good_source),
                VideoJob(clip_id="bad", source=bad_source),
            ]
            defaults = VideoDefaults()

            with patch.dict("os.environ", {"REPLICATE_API_TOKEN": "test-token"}):
                results = await generate_videos(
                    jobs=jobs,
                    run_dir=tmp_path,
                    defaults=defaults,
                    concurrency=2,
                    poll_sec=0.1,
                )

            # Good job should succeed, bad job should fail gracefully
            assert "good" in results
            assert "bad" not in results
        finally:
            batch_vid.MOCK_REPLICATE = original_mock


# ---------------------------------------------------------------------------
# extract_first_frame / extract_audio_track
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_video(tmp_path):
    """Create a short test video with audio using ffmpeg."""
    video_path = tmp_path / "test.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-shortest",
        str(video_path),
    ], capture_output=True, check=True)
    return video_path


class TestExtractFirstFrame:
    def test_extracts_frame(self, mock_video, tmp_path):
        dest = tmp_path / "output" / "frame.png"
        result = extract_first_frame(mock_video, dest)
        assert result == dest
        assert dest.exists()
        assert dest.stat().st_size > 0

    def test_creates_parent_dirs(self, mock_video, tmp_path):
        dest = tmp_path / "deep" / "nested" / "frame.png"
        extract_first_frame(mock_video, dest)
        assert dest.exists()


class TestExtractAudioTrack:
    def test_extracts_audio(self, mock_video, tmp_path):
        dest = tmp_path / "output" / "audio.aac"
        result = extract_audio_track(mock_video, dest)
        assert result == dest
        assert dest.exists()
        assert dest.stat().st_size > 0

    def test_creates_parent_dirs(self, mock_video, tmp_path):
        dest = tmp_path / "deep" / "nested" / "audio.aac"
        extract_audio_track(mock_video, dest)
        assert dest.exists()
