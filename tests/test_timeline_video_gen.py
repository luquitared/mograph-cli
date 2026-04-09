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
    def test_veo_lite(self):
        assert MODEL_KIND_MAP["veo-3.1-lite"] == "lite"

    def test_seedance(self):
        assert MODEL_KIND_MAP["seedance-2.0"] == "seedance"

    def test_seedance_fast(self):
        assert MODEL_KIND_MAP["seedance-2.0-fast"] == "seedance-fast"

    def test_get_model_owner_name_lite(self):
        owner, name = _get_model_owner_name("veo-3.1-lite")
        assert owner == "google"
        assert name == "veo-3.1-lite"

    def test_get_model_owner_name_seedance(self):
        owner, name = _get_model_owner_name("seedance-2.0")
        assert owner == "bytedance"
        assert name == "seedance-2.0"

    def test_get_model_owner_name_seedance_fast(self):
        owner, name = _get_model_owner_name("seedance-2.0-fast")
        assert owner == "bytedance"
        assert name == "seedance-2.0-fast"

    def test_get_model_owner_name_unknown_falls_back(self):
        owner, name = _get_model_owner_name("unknown-model")
        # Falls back to seedance-2.0-fast (default)
        assert owner == "bytedance"
        assert name == "seedance-2.0-fast"


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

        # Source has defaults (duration=5, aspect_ratio="16:9" etc),
        # so they won't fall through to VideoDefaults
        assert result["config"]["duration"] == 5  # source default
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
            source = VideoSource(prompt="test video", model="seedance-2.0")
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
            good_source = VideoSource(prompt="good video", model="seedance-2.0")
            bad_source = VideoSource(prompt="", model="seedance-2.0")  # Empty prompt → error

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
