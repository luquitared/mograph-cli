"""Tests for timeline image generation adapter."""

import asyncio
from pathlib import Path

import os

import pytest

import generation.batch_img as batch_img
from timeline.image_gen import generate_images, _build_request
from timeline.model import ImageDefaults, ImageSource, NodeResult


def test_build_request_sets_aspect_ratio():
    """aspect_ratio must always be explicitly set in config."""
    source = ImageSource(prompt="a cat", aspect_ratio="16:9", output_format="png")
    req = _build_request("clip_1", source, Path("/tmp/run"))
    assert req["config"]["aspect_ratio"] == "16:9"
    assert req["filename"] == "clip_1.png"
    assert req["output_dir"] == "/tmp/run/images"


def test_build_request_preserves_all_config_fields():
    source = ImageSource(
        prompt="test",
        aspect_ratio="4:3",
        resolution="1K",
        output_format="webp",
        safety_filter_level="block_none",
    )
    req = _build_request("clip_x", source, Path("/runs/test"))
    cfg = req["config"]
    assert cfg["aspect_ratio"] == "4:3"
    assert cfg["resolution"] == "1K"
    assert cfg["output_format"] == "webp"
    assert cfg["safety_filter_level"] == "block_none"


def test_source_fields_used_directly_without_defaults():
    """Parser already applies defaults; image_gen uses source fields as-is."""
    source = ImageSource(
        prompt="hi",
        aspect_ratio="16:9",
        resolution="2K",
        reference_images=["custom.png"],
    )
    req = _build_request("c1", source, Path("/tmp/run"))
    assert req["config"]["aspect_ratio"] == "16:9"
    assert req["config"]["resolution"] == "2K"
    assert req["reference_images"] == ["custom.png"]


def test_empty_reference_images_not_overridden():
    """An explicit empty list should stay empty (not fall back to defaults)."""
    source = ImageSource(prompt="hi", reference_images=[])
    req = _build_request("c1", source, Path("/tmp/run"))
    assert req["reference_images"] == []


def test_missing_replicate_token_raises(tmp_path, monkeypatch):
    """generate_images raises EnvironmentError when REPLICATE_API_TOKEN is missing and not mock mode."""
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    batch_img.MOCK_REPLICATE = False
    sources = [("c1", ImageSource(prompt="test", aspect_ratio="16:9"))]
    with pytest.raises(EnvironmentError, match="REPLICATE_API_TOKEN not set"):
        asyncio.run(generate_images(sources, tmp_path, ImageDefaults()))


def test_generate_images_mock_mode(tmp_path, monkeypatch):
    """End-to-end test with mock mode enabled."""
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    batch_img.MOCK_REPLICATE = True
    try:
        sources = [
            ("clip_1", ImageSource(prompt="a mountain landscape", aspect_ratio="16:9")),
            ("clip_2", ImageSource(prompt="a city skyline", aspect_ratio="16:9")),
        ]
        defaults = ImageDefaults()
        results = asyncio.run(
            generate_images(sources, tmp_path, defaults, concurrency=2)
        )

        assert len(results) == 2
        for clip_id in ("clip_1", "clip_2"):
            assert clip_id in results
            r = results[clip_id]
            assert isinstance(r, NodeResult)
            assert r.media_type == "image"
            assert r.duration is None
            assert r.path.exists()

        # Verify images dir was created
        assert (tmp_path / "images").is_dir()
    finally:
        batch_img.MOCK_REPLICATE = False


def test_generate_images_empty_sources(tmp_path):
    """Empty sources list returns empty dict."""
    defaults = ImageDefaults()
    results = asyncio.run(generate_images([], tmp_path, defaults))
    assert results == {}


def test_generate_images_error_handling(tmp_path, monkeypatch):
    """A failing source doesn't crash the entire batch."""
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    batch_img.MOCK_REPLICATE = True

    call_count = 0

    original_fn = batch_img.generate_single_image

    async def _patched(session, default_messages, request, idx, poll_sec, output_dir, **kw):
        nonlocal call_count
        call_count += 1
        if idx == 0:
            raise RuntimeError("Simulated failure")
        return await original_fn(session, default_messages, request, idx, poll_sec, output_dir, **kw)

    monkeypatch.setattr("timeline.image_gen.generate_single_image", _patched)
    try:
        sources = [
            ("fail_clip", ImageSource(prompt="will fail", aspect_ratio="16:9")),
            ("ok_clip", ImageSource(prompt="will succeed", aspect_ratio="16:9")),
        ]
        defaults = ImageDefaults()
        results = asyncio.run(
            generate_images(sources, tmp_path, defaults, concurrency=2)
        )

        # Only the successful one should be in results
        assert "fail_clip" not in results
        assert "ok_clip" in results
        assert results["ok_clip"].media_type == "image"
    finally:
        batch_img.MOCK_REPLICATE = False


def test_images_dir_created(tmp_path, monkeypatch):
    """run_dir/images/ directory is created even with no sources."""
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    batch_img.MOCK_REPLICATE = True
    try:
        sources = [("c1", ImageSource(prompt="test", aspect_ratio="16:9"))]
        defaults = ImageDefaults()
        asyncio.run(generate_images(sources, tmp_path, defaults))
        assert (tmp_path / "images").is_dir()
    finally:
        batch_img.MOCK_REPLICATE = False
