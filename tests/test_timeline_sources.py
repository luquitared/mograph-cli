"""Tests for timeline source adapters: file_source, silence_gen, still_gen."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from timeline.model import FileSource, NodeResult, Ref, SilenceSource, StillSource
from timeline.security import SecurityError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously for tests."""
    return asyncio.run(coro)


@pytest.fixture
def tmp_dirs(tmp_path):
    """Create run_dir and timeline_dir with a sample file."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    timeline_dir = tmp_path / "timeline"
    timeline_dir.mkdir()
    # Create a sample audio file
    sample = timeline_dir / "narration.mp3"
    sample.write_bytes(b"\x00" * 100)
    # Create a sample image
    img = timeline_dir / "frame.png"
    img.write_bytes(b"\x89PNG" + b"\x00" * 100)
    return run_dir, timeline_dir


# ---------------------------------------------------------------------------
# file_source tests
# ---------------------------------------------------------------------------

class TestFileSource:
    """Tests for timeline/file_source.py."""

    def test_local_file_resolution(self, tmp_dirs, monkeypatch):
        """Local file paths resolve relative to CWD."""
        from timeline.file_source import resolve_file_sources

        run_dir, timeline_dir = tmp_dirs
        source = FileSource(path="narration.mp3")

        # file_source resolves local paths relative to CWD
        monkeypatch.chdir(timeline_dir)

        with patch("timeline.file_source.probe_duration_async", new_callable=AsyncMock) as mock_probe:
            mock_probe.return_value = 5.0
            results = _run(resolve_file_sources(
                [("clip1", source)], run_dir, timeline_dir
            ))

        assert "clip1" in results
        r = results["clip1"]
        assert r.duration == 5.0
        assert r.media_type == "audio"
        assert r.path == (timeline_dir / "narration.mp3").resolve()

    def test_path_traversal_rejected(self, tmp_dirs):
        """Paths with .. components are rejected."""
        from timeline.file_source import resolve_file_sources

        run_dir, timeline_dir = tmp_dirs
        source = FileSource(path="../../etc/passwd")

        with pytest.raises(SecurityError, match="\\.\\."):
            _run(resolve_file_sources(
                [("clip1", source)], run_dir, timeline_dir
            ))

    def test_url_download(self, tmp_dirs):
        """URL sources are downloaded after SSRF validation."""
        from timeline.file_source import resolve_file_sources

        run_dir, timeline_dir = tmp_dirs
        source = FileSource(path="https://example.com/audio.mp3")

        with patch("timeline.file_source.validate_url") as mock_validate, \
             patch("timeline.file_source.probe_duration_async", new_callable=AsyncMock) as mock_probe, \
             patch("timeline.file_source._download_file", new_callable=AsyncMock) as mock_dl:

            mock_validate.return_value = ["93.184.216.34"]
            mock_probe.return_value = 10.0
            dl_dest = run_dir / "downloads" / "clip1_audio.mp3"
            dl_dest.parent.mkdir(parents=True, exist_ok=True)
            dl_dest.write_bytes(b"fake audio data")
            mock_dl.return_value = dl_dest

            results = _run(resolve_file_sources(
                [("clip1", source)], run_dir, timeline_dir
            ))

            # validate_url is called twice: once in resolve_file_sources for IP collection, once in _resolve_single
            assert mock_validate.call_count == 2
            assert "clip1" in results
            assert results["clip1"].media_type == "audio"
            assert results["clip1"].duration == 10.0

    def test_ssrf_private_ip_rejected(self, tmp_dirs):
        """URLs resolving to private IPs are rejected."""
        from timeline.file_source import resolve_file_sources

        run_dir, timeline_dir = tmp_dirs
        source = FileSource(path="http://169.254.169.254/latest/meta-data/")

        with pytest.raises(SecurityError):
            _run(resolve_file_sources(
                [("clip1", source)], run_dir, timeline_dir
            ))

    def test_segment_extraction(self, tmp_dirs, monkeypatch):
        """Files with start/end get segment extracted."""
        from timeline.file_source import resolve_file_sources

        run_dir, timeline_dir = tmp_dirs
        monkeypatch.chdir(timeline_dir)
        source = FileSource(path="narration.mp3", start=1.0, end=3.0)

        with patch("timeline.file_source.probe_duration_async", new_callable=AsyncMock), \
             patch("timeline.file_source.extract_audio_segment") as mock_extract:

            results = _run(resolve_file_sources(
                [("clip1", source)], run_dir, timeline_dir
            ))

            mock_extract.assert_called_once()
            args = mock_extract.call_args[0]
            assert args[1] == 1.0  # start
            assert args[2] == 3.0  # end
            assert results["clip1"].duration == 2.0

    def test_segment_no_end_probes_duration(self, tmp_dirs, monkeypatch):
        """Segment with start but no end probes full duration."""
        from timeline.file_source import resolve_file_sources

        run_dir, timeline_dir = tmp_dirs
        monkeypatch.chdir(timeline_dir)
        source = FileSource(path="narration.mp3", start=2.0)

        with patch("timeline.file_source.probe_duration_async", new_callable=AsyncMock) as mock_probe, \
             patch("timeline.file_source.extract_audio_segment"):
            mock_probe.return_value = 8.0
            results = _run(resolve_file_sources(
                [("clip1", source)], run_dir, timeline_dir
            ))
            assert results["clip1"].duration == 6.0  # 8.0 - 2.0

    def test_media_type_inference(self):
        """File extensions map to correct media types."""
        from timeline.file_source import _infer_media_type

        assert _infer_media_type(Path("clip.mp4")) == "video"
        assert _infer_media_type(Path("clip.mov")) == "video"
        assert _infer_media_type(Path("clip.webm")) == "video"
        assert _infer_media_type(Path("clip.mp3")) == "audio"
        assert _infer_media_type(Path("clip.wav")) == "audio"
        assert _infer_media_type(Path("clip.aac")) == "audio"
        assert _infer_media_type(Path("clip.png")) == "image"
        assert _infer_media_type(Path("clip.jpg")) == "image"
        assert _infer_media_type(Path("clip.jpeg")) == "image"

    def test_file_not_found(self, tmp_dirs):
        """Missing local files raise FileNotFoundError."""
        from timeline.file_source import resolve_file_sources

        run_dir, timeline_dir = tmp_dirs
        source = FileSource(path="nonexistent.mp3")

        with pytest.raises(FileNotFoundError, match="nonexistent.mp3"):
            _run(resolve_file_sources(
                [("clip1", source)], run_dir, timeline_dir
            ))

    def test_download_size_limit(self, tmp_dirs):
        """Downloads exceeding MAX_DOWNLOAD_SIZE are rejected."""
        from timeline.file_source import MAX_DOWNLOAD_SIZE, _download_file

        run_dir, _ = tmp_dirs
        dest = run_dir / "downloads" / "big_file.mp3"
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Create a mock response that yields chunks exceeding the limit
        chunk_size = 8192
        num_chunks = (MAX_DOWNLOAD_SIZE // chunk_size) + 2

        async def _test():
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = MagicMock()

            async def _iter_chunks(size):
                for _ in range(num_chunks):
                    yield b"\x00" * chunk_size

            mock_resp.content.iter_chunked = _iter_chunks
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=mock_resp)

            with pytest.raises(SecurityError, match="exceeds maximum size"):
                await _download_file("http://example.com/huge.bin", dest, mock_session)

            # File should be cleaned up
            assert not dest.exists()

        _run(_test())

    def test_concurrent_resolution(self, tmp_dirs, monkeypatch):
        """Multiple file sources are resolved concurrently via asyncio.gather."""
        from timeline.file_source import resolve_file_sources

        run_dir, timeline_dir = tmp_dirs
        monkeypatch.chdir(timeline_dir)
        # Create additional files
        (timeline_dir / "file2.mp3").write_bytes(b"\x00" * 50)
        (timeline_dir / "file3.mp3").write_bytes(b"\x00" * 50)

        sources = [
            ("clip1", FileSource(path="narration.mp3")),
            ("clip2", FileSource(path="file2.mp3")),
            ("clip3", FileSource(path="file3.mp3")),
        ]

        with patch("timeline.file_source.probe_duration_async", new_callable=AsyncMock) as mock_probe, \
             patch("timeline.file_source.asyncio.gather", wraps=asyncio.gather) as mock_gather:
            mock_probe.return_value = 5.0
            results = _run(resolve_file_sources(sources, run_dir, timeline_dir))

            assert len(results) == 3
            assert mock_gather.called


# ---------------------------------------------------------------------------
# silence_gen tests
# ---------------------------------------------------------------------------

class TestSilenceGen:
    """Tests for timeline/silence_gen.py."""

    def test_generate_silence(self, tmp_dirs):
        """Silence clips are generated with correct duration."""
        from timeline.silence_gen import generate_silence_clips

        run_dir, _ = tmp_dirs
        source = SilenceSource(duration=2.5)

        with patch("timeline.silence_gen.generate_silence") as mock_gen:
            results = _run(generate_silence_clips(
                [("sil1", source)], run_dir
            ))

        assert "sil1" in results
        r = results["sil1"]
        assert r.duration == 2.5
        assert r.media_type == "audio"
        assert "sil1_silence.wav" in str(r.path)
        mock_gen.assert_called_once()

    def test_minimum_duration(self, tmp_dirs):
        """Durations below 0.1 are clamped to 0.1."""
        from timeline.silence_gen import generate_silence_clips

        run_dir, _ = tmp_dirs
        source = SilenceSource(duration=0.01)

        with patch("timeline.silence_gen.generate_silence") as mock_gen:
            results = _run(generate_silence_clips(
                [("sil1", source)], run_dir
            ))

        assert results["sil1"].duration == 0.1
        args = mock_gen.call_args[0]
        assert args[0] == 0.1  # clamped duration

    def test_empty_sources(self, tmp_dirs):
        """Empty source list returns empty dict."""
        from timeline.silence_gen import generate_silence_clips

        run_dir, _ = tmp_dirs
        results = _run(generate_silence_clips([], run_dir))
        assert results == {}

    def test_multiple_silence_clips(self, tmp_dirs):
        """Multiple silence clips are all generated."""
        from timeline.silence_gen import generate_silence_clips

        run_dir, _ = tmp_dirs
        sources = [
            ("sil1", SilenceSource(duration=1.0)),
            ("sil2", SilenceSource(duration=3.0)),
        ]

        with patch("timeline.silence_gen.generate_silence"):
            results = _run(generate_silence_clips(sources, run_dir))

        assert len(results) == 2
        assert results["sil1"].duration == 1.0
        assert results["sil2"].duration == 3.0

    def test_concurrent_generation(self, tmp_dirs):
        """Multiple silence clips use asyncio.gather for concurrency."""
        from timeline.silence_gen import generate_silence_clips

        run_dir, _ = tmp_dirs
        sources = [
            ("sil1", SilenceSource(duration=1.0)),
            ("sil2", SilenceSource(duration=2.0)),
        ]

        with patch("timeline.silence_gen.generate_silence"), \
             patch("timeline.silence_gen.asyncio.gather", wraps=asyncio.gather) as mock_gather:
            results = _run(generate_silence_clips(sources, run_dir))

            assert len(results) == 2
            assert mock_gather.called


# ---------------------------------------------------------------------------
# still_gen tests
# ---------------------------------------------------------------------------

class TestStillGen:
    """Tests for timeline/still_gen.py."""

    def test_still_from_path(self, tmp_dirs):
        """Still source with string path creates video."""
        from timeline.still_gen import generate_still_videos

        run_dir, timeline_dir = tmp_dirs
        image_path = timeline_dir / "frame.png"
        source = StillSource(image=str(image_path), duration=3.0)

        with patch("timeline.still_gen.image_to_video_async", new_callable=AsyncMock) as mock_conv:
            results = _run(generate_still_videos(
                [("still1", source)], run_dir, {}
            ))

        assert "still1" in results
        r = results["still1"]
        assert r.duration == 3.0
        assert r.media_type == "video"
        assert "still1_still.mp4" in str(r.path)
        mock_conv.assert_called_once()

    def test_still_from_ref(self, tmp_dirs):
        """Still source with Ref resolves from results dict."""
        from timeline.still_gen import generate_still_videos

        run_dir, timeline_dir = tmp_dirs
        image_path = timeline_dir / "frame.png"

        existing_results = {
            "img1": NodeResult(path=image_path, duration=None, media_type="image"),
        }
        source = StillSource(image=Ref(ref="img1"), duration=5.0)

        with patch("timeline.still_gen.image_to_video_async", new_callable=AsyncMock):
            results = _run(generate_still_videos(
                [("still1", source)], run_dir, existing_results
            ))

        assert results["still1"].duration == 5.0

    def test_still_unresolved_ref(self, tmp_dirs):
        """Ref to missing clip raises ValueError."""
        from timeline.still_gen import generate_still_videos

        run_dir, _ = tmp_dirs
        source = StillSource(image=Ref(ref="missing"), duration=2.0)

        with pytest.raises(ValueError, match="unresolved clip"):
            _run(generate_still_videos(
                [("still1", source)], run_dir, {}
            ))

    def test_still_image_not_found(self, tmp_dirs):
        """Missing image file raises FileNotFoundError."""
        from timeline.still_gen import generate_still_videos

        run_dir, _ = tmp_dirs
        source = StillSource(image="/nonexistent/image.png", duration=2.0)

        with pytest.raises(FileNotFoundError):
            _run(generate_still_videos(
                [("still1", source)], run_dir, {}
            ))

    def test_empty_sources(self, tmp_dirs):
        """Empty source list returns empty dict."""
        from timeline.still_gen import generate_still_videos

        run_dir, _ = tmp_dirs
        results = _run(generate_still_videos([], run_dir, {}))
        assert results == {}

    def test_concurrent_generation(self, tmp_dirs):
        """Multiple still clips use asyncio.gather for concurrency."""
        from timeline.still_gen import generate_still_videos

        run_dir, timeline_dir = tmp_dirs
        image_path = timeline_dir / "frame.png"

        sources = [
            ("still1", StillSource(image=str(image_path), duration=2.0)),
            ("still2", StillSource(image=str(image_path), duration=3.0)),
        ]

        with patch("timeline.still_gen.image_to_video_async", new_callable=AsyncMock), \
             patch("timeline.still_gen.asyncio.gather", wraps=asyncio.gather) as mock_gather:
            results = _run(generate_still_videos(sources, run_dir, {}))

            assert len(results) == 2
            assert mock_gather.called


# ---------------------------------------------------------------------------
# Async helper for mocking aiohttp response iteration
# ---------------------------------------------------------------------------

async def _async_iter(items):
    for item in items:
        yield item
