"""Tests for timeline/assembler.py — assembly pipeline."""

import asyncio
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from timeline.model import (
    Clip,
    NodeResult,
    Output,
    OutputVariants,
    Project,
    Timeline,
    Track,
    VideoSource,
    TTSSource,
)
from timeline.timing import ClipLayout, TimelineLayout
from timeline.assembler import assemble_timeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_timeline(
    video_clips=None,
    narration_clips=None,
    audio_tracks=None,
    variants=None,
    narration_volume=1.0,
    sfx_volume=0.3,
):
    """Build a timeline with specified tracks."""
    tracks = []
    if video_clips:
        tracks.append(Track(id="video", type="video", clips=video_clips))
    if narration_clips:
        tracks.append(Track(id="narration", type="narration", clips=narration_clips))
    if audio_tracks:
        tracks.extend(audio_tracks)

    if variants is None:
        variants = OutputVariants()

    return Timeline(
        version=1,
        project=Project(name="Test"),
        tracks=tracks,
        output=Output(
            variants=variants,
            narration_volume=narration_volume,
            sfx_volume=sfx_volume,
        ),
    )


def _make_results(clip_ids, tmp_path, media_type="video", ext=".mp4"):
    """Create fake result files and NodeResult entries."""
    results = {}
    for cid in clip_ids:
        p = tmp_path / f"{cid}{ext}"
        p.write_bytes(b"\x00" * 100)
        results[cid] = NodeResult(path=p, duration=5.0, media_type=media_type)
    return results


def _make_layout(clip_ids, duration=5.0):
    """Create a simple TimelineLayout."""
    clips = {}
    for cid in clip_ids:
        clips[cid] = ClipLayout(
            clip_id=cid,
            track_id="video",
            start_time=0.0,
            raw_duration=duration,
            final_duration=duration,
            fit_to=None,
            fit_method="speed",
            buffer_ms=0.0,
            needs_fit=False,
        )
    return TimelineLayout(clips=clips, track_order=["video"], total_duration=duration)


# ---------------------------------------------------------------------------
# Video concatenation (REQ-ASSM-001)
# ---------------------------------------------------------------------------

class TestVideoConcatenation:
    @pytest.mark.asyncio
    async def test_concat_multiple_videos(self, tmp_path):
        """Multiple video clips are concatenated."""
        clips = [
            Clip(id="v1", source=VideoSource(prompt="a")),
            Clip(id="v2", source=VideoSource(prompt="b")),
        ]
        results = _make_results(["v1", "v2"], tmp_path)
        layout = _make_layout(["v1", "v2"])
        timeline = _make_timeline(video_clips=clips, narration_clips=[
            Clip(id="n1", source=TTSSource(text="hello")),
        ])
        narr_results = _make_results(["n1"], tmp_path, media_type="audio", ext=".wav")
        results.update(narr_results)

        with patch("timeline.assembler.media") as mock_media:
            mock_media.concat_videos_async = AsyncMock()
            mock_media.overlay_audio_async = AsyncMock()
            mock_media.concat_audio = MagicMock()
            mock_media.extract_audio_track = MagicMock()

            await assemble_timeline(timeline, results, layout, tmp_path)

            mock_media.concat_videos_async.assert_called_once()
            call_args = mock_media.concat_videos_async.call_args
            assert len(call_args[0][0]) == 2  # two video paths

    @pytest.mark.asyncio
    async def test_single_video_no_concat(self, tmp_path):
        """Single video clip is copied, not concatenated."""
        clips = [Clip(id="v1", source=VideoSource(prompt="a"))]
        results = _make_results(["v1"], tmp_path)
        narr_clips = [Clip(id="n1", source=TTSSource(text="hello"))]
        narr_results = _make_results(["n1"], tmp_path, media_type="audio", ext=".wav")
        results.update(narr_results)
        layout = _make_layout(["v1"])
        timeline = _make_timeline(
            video_clips=clips, narration_clips=narr_clips,
            variants=OutputVariants(narration_only=True, narration_sfx=False, images_only=False),
        )

        with patch("timeline.assembler.media") as mock_media:
            mock_media.overlay_audio_async = AsyncMock()
            mock_media.concat_audio = MagicMock()
            mock_media.extract_audio_track = MagicMock()

            await assemble_timeline(timeline, results, layout, tmp_path)

            # concat_videos_async should NOT be called for single video
            mock_media.concat_videos_async.assert_not_called()
            # But overlay should be called (narration-only variant)
            mock_media.overlay_audio_async.assert_called_once()


# ---------------------------------------------------------------------------
# Narration concatenation (REQ-ASSM-002)
# ---------------------------------------------------------------------------

class TestNarrationConcatenation:
    @pytest.mark.asyncio
    async def test_concat_multiple_narrations(self, tmp_path):
        """Multiple narration clips are concatenated."""
        narr_clips = [
            Clip(id="n1", source=TTSSource(text="hello")),
            Clip(id="n2", source=TTSSource(text="world")),
        ]
        video_clips = [Clip(id="v1", source=VideoSource(prompt="a"))]
        results = _make_results(["v1"], tmp_path)
        narr_results = _make_results(["n1", "n2"], tmp_path, media_type="audio", ext=".wav")
        results.update(narr_results)
        layout = _make_layout(["v1"])
        timeline = _make_timeline(video_clips=video_clips, narration_clips=narr_clips)

        with patch("timeline.assembler.media") as mock_media:
            mock_media.concat_audio = MagicMock()
            mock_media.overlay_audio_async = AsyncMock()
            mock_media.extract_audio_track = MagicMock()

            await assemble_timeline(timeline, results, layout, tmp_path)

            mock_media.concat_audio.assert_called_once()
            call_args = mock_media.concat_audio.call_args
            assert len(call_args[0][0]) == 2  # two narration paths

    @pytest.mark.asyncio
    async def test_single_narration_no_concat(self, tmp_path):
        """Single narration clip is copied, not concatenated."""
        narr_clips = [Clip(id="n1", source=TTSSource(text="hello"))]
        video_clips = [Clip(id="v1", source=VideoSource(prompt="a"))]
        results = _make_results(["v1"], tmp_path)
        narr_results = _make_results(["n1"], tmp_path, media_type="audio", ext=".wav")
        results.update(narr_results)
        layout = _make_layout(["v1"])
        timeline = _make_timeline(video_clips=video_clips, narration_clips=narr_clips)

        with patch("timeline.assembler.media") as mock_media:
            mock_media.overlay_audio_async = AsyncMock()
            mock_media.extract_audio_track = MagicMock()

            await assemble_timeline(timeline, results, layout, tmp_path)

            # concat_audio should NOT be called for single narration
            mock_media.concat_audio.assert_not_called()


# ---------------------------------------------------------------------------
# Narration-only variant (REQ-ASSM-003)
# ---------------------------------------------------------------------------

class TestNarrationOnlyVariant:
    @pytest.mark.asyncio
    async def test_narration_only_produced(self, tmp_path):
        """Narration-only variant calls overlay_audio_async."""
        video_clips = [Clip(id="v1", source=VideoSource(prompt="a"))]
        narr_clips = [Clip(id="n1", source=TTSSource(text="hello"))]
        results = _make_results(["v1"], tmp_path)
        results.update(_make_results(["n1"], tmp_path, media_type="audio", ext=".wav"))
        layout = _make_layout(["v1"])
        timeline = _make_timeline(
            video_clips=video_clips,
            narration_clips=narr_clips,
            variants=OutputVariants(narration_only=True, narration_sfx=False, images_only=False),
        )

        with patch("timeline.assembler.media") as mock_media:
            mock_media.overlay_audio_async = AsyncMock()
            mock_media.extract_audio_track = MagicMock()

            result = await assemble_timeline(timeline, results, layout, tmp_path)

            assert "narration_only" in result
            mock_media.overlay_audio_async.assert_called_once()
            dest = mock_media.overlay_audio_async.call_args[0][2]
            assert dest.name == "final.mp4"

    @pytest.mark.asyncio
    async def test_narration_only_disabled(self, tmp_path):
        """When narration_only is False, no narration-only variant is produced."""
        video_clips = [Clip(id="v1", source=VideoSource(prompt="a"))]
        narr_clips = [Clip(id="n1", source=TTSSource(text="hello"))]
        results = _make_results(["v1"], tmp_path)
        results.update(_make_results(["n1"], tmp_path, media_type="audio", ext=".wav"))
        layout = _make_layout(["v1"])
        timeline = _make_timeline(
            video_clips=video_clips,
            narration_clips=narr_clips,
            variants=OutputVariants(narration_only=False, narration_sfx=False, images_only=False),
        )

        with patch("timeline.assembler.media") as mock_media:
            mock_media.extract_audio_track = MagicMock()

            result = await assemble_timeline(timeline, results, layout, tmp_path)

            assert "narration_only" not in result


# ---------------------------------------------------------------------------
# SFX extraction from pre-fit videos (REQ-ASSM-004, REQ-ASSM-007, REQ-ASSM-008)
# ---------------------------------------------------------------------------

class TestSFXVariant:
    @pytest.mark.asyncio
    async def test_sfx_extracts_from_original_videos(self, tmp_path):
        """SFX is extracted from original videos in videos/ dir, not adjusted."""
        video_clips = [Clip(id="v1", source=VideoSource(prompt="a"))]
        narr_clips = [Clip(id="n1", source=TTSSource(text="hello"))]
        results = _make_results(["v1"], tmp_path)
        results.update(_make_results(["n1"], tmp_path, media_type="audio", ext=".wav"))
        layout = _make_layout(["v1"])

        # Create original video in videos/ dir
        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        original = videos_dir / "v1.mp4"
        original.write_bytes(b"\x00" * 100)

        timeline = _make_timeline(
            video_clips=video_clips,
            narration_clips=narr_clips,
            variants=OutputVariants(narration_only=False, narration_sfx=True, images_only=False),
        )

        with patch("timeline.assembler.media") as mock_media:
            mock_media.overlay_combined_audio_async = AsyncMock()
            mock_media.extract_audio_track = MagicMock(side_effect=lambda v, d: d.write_bytes(b"\x00"))
            mock_media.concat_audio = MagicMock()

            result = await assemble_timeline(timeline, results, layout, tmp_path)

            assert "narration_sfx" in result
            # extract_audio_track should be called with original video path
            mock_media.extract_audio_track.assert_called_once()
            call_video_path = mock_media.extract_audio_track.call_args[0][0]
            assert call_video_path == original

    @pytest.mark.asyncio
    async def test_sfx_fallback_when_no_original(self, tmp_path):
        """When no original video exists, falls back to narration-only overlay."""
        video_clips = [Clip(id="v1", source=VideoSource(prompt="a"))]
        narr_clips = [Clip(id="n1", source=TTSSource(text="hello"))]
        results = _make_results(["v1"], tmp_path)
        results.update(_make_results(["n1"], tmp_path, media_type="audio", ext=".wav"))
        layout = _make_layout(["v1"])
        # No videos/ dir — no original videos

        timeline = _make_timeline(
            video_clips=video_clips,
            narration_clips=narr_clips,
            variants=OutputVariants(narration_only=False, narration_sfx=True, images_only=False),
        )

        with patch("timeline.assembler.media") as mock_media:
            mock_media.overlay_audio_async = AsyncMock()

            result = await assemble_timeline(timeline, results, layout, tmp_path)

            assert "narration_sfx" in result
            # Should fall back to overlay_audio_async (no SFX found)
            mock_media.overlay_audio_async.assert_called_once()


# ---------------------------------------------------------------------------
# Images-only variant (REQ-ASSM-005)
# ---------------------------------------------------------------------------

class TestImagesOnlyVariant:
    @pytest.mark.asyncio
    async def test_images_only_from_images_dir(self, tmp_path):
        """Images-only variant finds images in images/ directory."""
        video_clips = [Clip(id="v1", source=VideoSource(prompt="a"))]
        narr_clips = [Clip(id="n1", source=TTSSource(text="hello"))]
        results = _make_results(["v1"], tmp_path)
        results.update(_make_results(["n1"], tmp_path, media_type="audio", ext=".wav"))
        layout = _make_layout(["v1"])

        # Create image in images/ dir
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        (images_dir / "v1.png").write_bytes(b"\x89PNG" + b"\x00" * 100)

        timeline = _make_timeline(
            video_clips=video_clips,
            narration_clips=narr_clips,
            variants=OutputVariants(narration_only=False, narration_sfx=False, images_only=True),
        )

        with patch("timeline.assembler.media") as mock_media:
            mock_media.image_to_video_async = AsyncMock()
            mock_media.overlay_audio_async = AsyncMock()
            mock_media.concat_videos_async = AsyncMock()

            result = await assemble_timeline(timeline, results, layout, tmp_path)

            assert "images_only" in result
            mock_media.image_to_video_async.assert_called_once()
            # Check it used the image from images/
            call_args = mock_media.image_to_video_async.call_args[0]
            assert call_args[0] == images_dir / "v1.png"
            assert call_args[1] == 5.0  # duration from layout

    @pytest.mark.asyncio
    async def test_images_only_fallback_extract_frame(self, tmp_path):
        """Falls back to extracting first frame when no image in images/ dir."""
        video_clips = [Clip(id="v1", source=VideoSource(prompt="a"))]
        narr_clips = [Clip(id="n1", source=TTSSource(text="hello"))]
        results = _make_results(["v1"], tmp_path)
        results.update(_make_results(["n1"], tmp_path, media_type="audio", ext=".wav"))
        layout = _make_layout(["v1"])
        # No images/ dir

        timeline = _make_timeline(
            video_clips=video_clips,
            narration_clips=narr_clips,
            variants=OutputVariants(narration_only=False, narration_sfx=False, images_only=True),
        )

        with patch("timeline.assembler.media") as mock_media:
            # extract_first_frame writes a file
            def fake_extract(video_path, dest):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"\x89PNG" + b"\x00" * 50)
                return dest

            mock_media.extract_first_frame = MagicMock(side_effect=fake_extract)
            mock_media.image_to_video_async = AsyncMock()
            mock_media.overlay_audio_async = AsyncMock()
            mock_media.concat_videos_async = AsyncMock()

            result = await assemble_timeline(timeline, results, layout, tmp_path)

            assert "images_only" in result
            mock_media.extract_first_frame.assert_called_once()


# ---------------------------------------------------------------------------
# Variant toggling
# ---------------------------------------------------------------------------

class TestVariantToggling:
    @pytest.mark.asyncio
    async def test_all_variants_disabled(self, tmp_path):
        """When all variants are disabled, no outputs are produced."""
        video_clips = [Clip(id="v1", source=VideoSource(prompt="a"))]
        narr_clips = [Clip(id="n1", source=TTSSource(text="hello"))]
        results = _make_results(["v1"], tmp_path)
        results.update(_make_results(["n1"], tmp_path, media_type="audio", ext=".wav"))
        layout = _make_layout(["v1"])

        timeline = _make_timeline(
            video_clips=video_clips,
            narration_clips=narr_clips,
            variants=OutputVariants(narration_only=False, narration_sfx=False, images_only=False),
        )

        with patch("timeline.assembler.media") as mock_media:
            result = await assemble_timeline(timeline, results, layout, tmp_path)

        assert result == {}

    @pytest.mark.asyncio
    async def test_only_sfx_enabled(self, tmp_path):
        """Only SFX variant produces output when others are disabled."""
        video_clips = [Clip(id="v1", source=VideoSource(prompt="a"))]
        narr_clips = [Clip(id="n1", source=TTSSource(text="hello"))]
        results = _make_results(["v1"], tmp_path)
        results.update(_make_results(["n1"], tmp_path, media_type="audio", ext=".wav"))
        layout = _make_layout(["v1"])

        timeline = _make_timeline(
            video_clips=video_clips,
            narration_clips=narr_clips,
            variants=OutputVariants(narration_only=False, narration_sfx=True, images_only=False),
        )

        with patch("timeline.assembler.media") as mock_media:
            mock_media.overlay_audio_async = AsyncMock()
            mock_media.extract_audio_track = MagicMock()

            result = await assemble_timeline(timeline, results, layout, tmp_path)

            assert "narration_sfx" in result
            assert "narration_only" not in result


# ---------------------------------------------------------------------------
# Output directory creation (REQ-ASSM-012)
# ---------------------------------------------------------------------------

class TestOutputDirectory:
    @pytest.mark.asyncio
    async def test_final_dir_created(self, tmp_path):
        """The final/ directory is created even with no clips."""
        timeline = _make_timeline()
        layout = TimelineLayout(clips={}, track_order=[], total_duration=0.0)

        with patch("timeline.assembler.media"):
            await assemble_timeline(timeline, {}, layout, tmp_path)

        assert (tmp_path / "final").is_dir()


# ---------------------------------------------------------------------------
# Parser: output variants and track volume
# ---------------------------------------------------------------------------

from timeline.parser import TimelineParseError, parse_timeline


def _minimal_timeline_dict(**overrides) -> dict:
    base = {
        "version": 1,
        "project": {"name": "Test"},
        "tracks": [{"id": "main", "type": "video", "clips": [
            {"id": "c1", "source": {"type": "video", "prompt": "test"}}
        ]}],
    }
    base.update(overrides)
    return base


class TestParserOutputVariants:
    def test_parse_output_with_variants(self):
        data = _minimal_timeline_dict(output={
            "format": "mp4",
            "variants": {
                "narration_only": True,
                "narration_sfx": False,
                "images_only": True,
            },
            "narration_volume": 0.8,
            "sfx_volume": 0.2,
        })
        tl = parse_timeline(data)
        assert tl.output.variants.narration_only is True
        assert tl.output.variants.narration_sfx is False
        assert tl.output.variants.images_only is True
        assert tl.output.narration_volume == 0.8
        assert tl.output.sfx_volume == 0.2

    def test_parse_output_defaults_when_no_variants(self):
        data = _minimal_timeline_dict()
        tl = parse_timeline(data)
        assert tl.output.variants.narration_only is True
        assert tl.output.variants.narration_sfx is True
        assert tl.output.variants.images_only is False
        assert tl.output.narration_volume == 1.0
        assert tl.output.sfx_volume == 0.3

    def test_parse_output_partial_variants(self):
        data = _minimal_timeline_dict(output={
            "variants": {"images_only": True},
        })
        tl = parse_timeline(data)
        assert tl.output.variants.narration_only is True  # default
        assert tl.output.variants.images_only is True


class TestParserTrackVolume:
    def test_parse_track_with_volume(self):
        data = _minimal_timeline_dict(tracks=[
            {
                "id": "audio-1",
                "type": "audio",
                "volume": 0.5,
                "clips": [],
            }
        ])
        tl = parse_timeline(data)
        assert tl.tracks[0].volume == 0.5

    def test_parse_track_volume_default_none(self):
        data = _minimal_timeline_dict()
        tl = parse_timeline(data)
        assert tl.tracks[0].volume is None

    def test_parse_track_volume_invalid_range(self):
        data = _minimal_timeline_dict(tracks=[
            {"id": "a", "type": "audio", "volume": 1.5, "clips": []}
        ])
        with pytest.raises(TimelineParseError, match="volume"):
            parse_timeline(data)

    def test_parse_track_volume_negative(self):
        data = _minimal_timeline_dict(tracks=[
            {"id": "a", "type": "audio", "volume": -0.1, "clips": []}
        ])
        with pytest.raises(TimelineParseError, match="volume"):
            parse_timeline(data)

    def test_parse_track_volume_zero(self):
        data = _minimal_timeline_dict(tracks=[
            {"id": "a", "type": "audio", "volume": 0.0, "clips": []}
        ])
        tl = parse_timeline(data)
        assert tl.tracks[0].volume == 0.0

    def test_parse_track_volume_one(self):
        data = _minimal_timeline_dict(tracks=[
            {"id": "a", "type": "audio", "volume": 1.0, "clips": []}
        ])
        tl = parse_timeline(data)
        assert tl.tracks[0].volume == 1.0
