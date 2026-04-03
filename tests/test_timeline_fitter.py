"""Tests for timeline/fitter.py — fit adjustment module."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from timeline.fitter import DURATION_TOLERANCE, apply_fit, apply_fit_sync


@pytest.fixture
def run_dir(tmp_path):
    return tmp_path / "run"


@pytest.fixture
def clip_path(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"\x00")
    return p


@pytest.fixture
def audio_path(tmp_path):
    p = tmp_path / "clip.wav"
    p.write_bytes(b"\x00")
    return p


# --- speed method ---

@patch("timeline.fitter.change_video_speed_async", new_callable=AsyncMock)
def test_speed_video_correct_factor(mock_speed, run_dir, clip_path):
    result = asyncio.run(apply_fit(clip_path, "speed", 10.0, 5.0, "video", run_dir, "c1"))
    expected_dest = run_dir / "videos_adjusted" / "c1.mp4"
    mock_speed.assert_called_once_with(clip_path, 2.0, expected_dest)
    assert result == expected_dest


@patch("timeline.fitter.change_audio_speed")
def test_speed_audio_correct_factor(mock_speed, run_dir, audio_path):
    result = asyncio.run(apply_fit(audio_path, "speed", 8.0, 4.0, "audio", run_dir, "a1"))
    expected_dest = run_dir / "audio" / "a1_fitted.wav"
    mock_speed.assert_called_once_with(audio_path, 2.0, expected_dest, preserve_pitch=True)
    assert result == expected_dest


def test_speed_factor_too_high(run_dir, clip_path):
    # raw=50, target=1 → factor=50.0 (> 4.0)
    with pytest.raises(ValueError, match="outside allowed range"):
        asyncio.run(apply_fit(clip_path, "speed", 50.0, 1.0, "video", run_dir, "c1"))


def test_speed_factor_too_low(run_dir, clip_path):
    # raw=1, target=50 → factor=0.02 (< 0.25)
    with pytest.raises(ValueError, match="outside allowed range"):
        asyncio.run(apply_fit(clip_path, "speed", 1.0, 50.0, "video", run_dir, "c1"))


@patch("timeline.fitter.change_video_speed_async", new_callable=AsyncMock)
def test_speed_video_dest_path(mock_speed, run_dir, clip_path):
    result = asyncio.run(apply_fit(clip_path, "speed", 6.0, 3.0, "video", run_dir, "scene_02"))
    assert result == run_dir / "videos_adjusted" / "scene_02.mp4"


# --- extend method ---

@patch("timeline.fitter.extend_video_async", new_callable=AsyncMock)
def test_extend_video_shorter(mock_extend, run_dir, clip_path):
    result = asyncio.run(apply_fit(clip_path, "extend", 5.0, 8.0, "video", run_dir, "c1"))
    expected_dest = run_dir / "videos_adjusted" / "c1.mp4"
    mock_extend.assert_called_once_with(clip_path, 3.0, expected_dest)
    assert result == expected_dest


@patch("timeline.fitter.trim_video_async", new_callable=AsyncMock)
def test_extend_video_longer(mock_trim, run_dir, clip_path):
    result = asyncio.run(apply_fit(clip_path, "extend", 10.0, 7.0, "video", run_dir, "c1"))
    expected_dest = run_dir / "videos_adjusted" / "c1.mp4"
    mock_trim.assert_called_once_with(clip_path, 7.0, expected_dest)
    assert result == expected_dest


@patch("timeline.fitter.concat_audio")
@patch("timeline.fitter.generate_silence")
def test_extend_audio_shorter(mock_silence, mock_concat, run_dir, audio_path):
    result = asyncio.run(apply_fit(audio_path, "extend", 3.0, 5.0, "audio", run_dir, "a1"))
    expected_dest = run_dir / "audio" / "a1_fitted.wav"
    silence_path = run_dir / "audio" / "a1_silence.wav"
    mock_silence.assert_called_once_with(2.0, silence_path)
    mock_concat.assert_called_once_with([audio_path, silence_path], expected_dest, reencode=True)
    assert result == expected_dest


@patch("timeline.fitter.run_cmd")
def test_extend_audio_longer(mock_cmd, run_dir, audio_path):
    result = asyncio.run(apply_fit(audio_path, "extend", 10.0, 6.0, "audio", run_dir, "a1"))
    expected_dest = run_dir / "audio" / "a1_fitted.wav"
    mock_cmd.assert_called_once()
    cmd_args = mock_cmd.call_args[0][0]
    assert cmd_args[0] == "ffmpeg"
    assert "-t" in cmd_args
    assert str(6.0) in cmd_args
    assert result == expected_dest


# --- trim method ---

@patch("timeline.fitter.trim_video_async", new_callable=AsyncMock)
def test_trim_video_longer(mock_trim, run_dir, clip_path):
    result = asyncio.run(apply_fit(clip_path, "trim", 10.0, 7.0, "video", run_dir, "c1"))
    expected_dest = run_dir / "videos_adjusted" / "c1.mp4"
    mock_trim.assert_called_once_with(clip_path, 7.0, expected_dest)
    assert result == expected_dest


def test_trim_shorter_noop(run_dir, clip_path):
    result = asyncio.run(apply_fit(clip_path, "trim", 5.0, 10.0, "video", run_dir, "c1"))
    assert result == clip_path


@patch("timeline.fitter.run_cmd")
def test_trim_audio_longer(mock_cmd, run_dir, audio_path):
    result = asyncio.run(apply_fit(audio_path, "trim", 10.0, 6.0, "audio", run_dir, "a1"))
    expected_dest = run_dir / "audio" / "a1_fitted.wav"
    mock_cmd.assert_called_once()
    assert result == expected_dest


# --- tolerance / no-op ---

def test_noop_within_tolerance(run_dir, clip_path):
    result = asyncio.run(apply_fit(clip_path, "speed", 5.0, 5.03, "video", run_dir, "c1"))
    assert result == clip_path


@patch("timeline.fitter.extend_video_async", new_callable=AsyncMock)
def test_extend_exact_match_within_tolerance(mock_extend, run_dir, clip_path):
    result = asyncio.run(apply_fit(clip_path, "extend", 5.0, 5.04, "video", run_dir, "c1"))
    assert result == clip_path
    mock_extend.assert_not_called()


# --- error handling ---

def test_invalid_method(run_dir, clip_path):
    with pytest.raises(ValueError, match="Invalid fit method"):
        asyncio.run(apply_fit(clip_path, "stretch", 5.0, 10.0, "video", run_dir, "c1"))


def test_missing_file(run_dir, tmp_path):
    missing = tmp_path / "nonexistent.mp4"
    with pytest.raises(FileNotFoundError):
        asyncio.run(apply_fit(missing, "speed", 5.0, 10.0, "video", run_dir, "c1"))


# --- sync wrapper ---

@patch("timeline.fitter.change_video_speed_async", new_callable=AsyncMock)
def test_apply_fit_sync(mock_speed, run_dir, clip_path):
    result = apply_fit_sync(clip_path, "speed", 10.0, 5.0, "video", run_dir, "c1")
    expected_dest = run_dir / "videos_adjusted" / "c1.mp4"
    assert result == expected_dest
    mock_speed.assert_called_once()
