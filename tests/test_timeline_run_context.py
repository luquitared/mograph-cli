"""Tests for timeline.run_context — run directory setup and persistence."""

import json
import time
from pathlib import Path

import pytest

from timeline.run_context import (
    create_run_dir,
    is_stage_complete,
    load_metrics,
    load_run_config,
    mark_stage_complete,
    record_cost,
    save_metrics,
    save_run_config,
    save_timeline_copy,
    start_stage_timer,
    RUN_SUBDIRS,
)


# ---------------------------------------------------------------------------
# Run directory creation
# ---------------------------------------------------------------------------


def test_resolver_uses_extracted_frames_dir(tmp_path: Path):
    """Verify resolver writes to extracted_frames, matching run_context's pre-created dir."""
    from unittest.mock import patch
    from timeline.resolver import resolve_ref
    from timeline.model import Ref, NodeResult

    run_dir = create_run_dir("test", base_dir=tmp_path)
    results = {"vid1": NodeResult(path=Path(run_dir / "videos" / "vid1.mp4"), duration=6.0, media_type="video")}
    (run_dir / "videos" / "vid1.mp4").touch()

    ref = Ref(ref="vid1", extract="first_frame")
    with patch("shared.media.extract_first_frame") as mock_extract:
        mock_extract.return_value = None
        dest = resolve_ref(ref, results, run_dir)
        assert dest.parent.name == "extracted_frames"


def test_create_run_dir_creates_all_subdirs(tmp_path: Path):
    run_dir = create_run_dir("my-project", base_dir=tmp_path)
    assert run_dir.exists()
    assert "my-project-" in run_dir.name
    for subdir in RUN_SUBDIRS:
        assert (run_dir / subdir).is_dir(), f"Missing subdir: {subdir}"


def test_create_run_dir_sanitizes_project_name(tmp_path: Path):
    run_dir = create_run_dir("../../evil", base_dir=tmp_path)
    assert "______evil" in run_dir.name
    # Ensure the directory is actually inside tmp_path
    assert run_dir.parent == tmp_path


def test_create_run_dir_sanitizes_dots_and_slashes(tmp_path: Path):
    run_dir = create_run_dir("my project/v2.0", base_dir=tmp_path)
    assert "/" not in run_dir.name.split("-")[0]
    assert " " not in run_dir.name.split("-")[0]


def test_create_run_dir_empty_name_becomes_untitled(tmp_path: Path):
    run_dir = create_run_dir("...", base_dir=tmp_path)
    assert run_dir.name.startswith("___-")


def test_create_run_dir_fully_empty_name(tmp_path: Path):
    run_dir = create_run_dir("", base_dir=tmp_path)
    assert run_dir.name.startswith("untitled-")


def test_create_run_dir_uses_default_base_dir(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir = create_run_dir("test-proj")
    assert run_dir.exists()
    assert run_dir.parent.name == "runs"


# ---------------------------------------------------------------------------
# Timeline copy
# ---------------------------------------------------------------------------


def test_save_timeline_copy(tmp_path: Path):
    run_dir = create_run_dir("tl-test", base_dir=tmp_path)
    timeline = {"project": {"name": "demo"}, "tracks": []}
    path = save_timeline_copy(run_dir, timeline)
    assert path.name == "timeline.json"
    assert json.loads(path.read_text()) == timeline


# ---------------------------------------------------------------------------
# Config save/load round-trip
# ---------------------------------------------------------------------------


def test_config_save_load_roundtrip(tmp_path: Path):
    run_dir = create_run_dir("cfg-test", base_dir=tmp_path)
    config = {"completed_stages": [], "video_model": "veo", "extra": 42}
    save_run_config(run_dir, config)
    loaded = load_run_config(run_dir)
    assert loaded == config


def test_load_run_config_returns_empty_when_missing(tmp_path: Path):
    assert load_run_config(tmp_path) == {}


# ---------------------------------------------------------------------------
# Stage completion
# ---------------------------------------------------------------------------


def test_mark_and_check_stage_complete(tmp_path: Path):
    run_dir = create_run_dir("stage-test", base_dir=tmp_path)
    assert not is_stage_complete(run_dir, "images")
    mark_stage_complete(run_dir, "images")
    assert is_stage_complete(run_dir, "images")
    assert not is_stage_complete(run_dir, "videos")


def test_mark_stage_complete_is_idempotent(tmp_path: Path):
    run_dir = create_run_dir("idem-test", base_dir=tmp_path)
    mark_stage_complete(run_dir, "images")
    mark_stage_complete(run_dir, "images")
    config = load_run_config(run_dir)
    assert config["completed_stages"].count("images") == 1


# ---------------------------------------------------------------------------
# Cost recording and accumulation
# ---------------------------------------------------------------------------


def test_record_cost_single(tmp_path: Path):
    run_dir = create_run_dir("cost-test", base_dir=tmp_path)
    record_cost(run_dir, "image_generation", 0.15, "scene01", {"prompt": "a cat"})
    metrics = load_metrics(run_dir)
    assert len(metrics["costs"]["items"]) == 1
    assert metrics["costs"]["total_usd"] == 0.15
    assert metrics["costs"]["by_category"]["image_generation"] == 0.15
    entry = metrics["costs"]["items"][0]
    assert entry["label"] == "scene01"
    assert entry["category"] == "image_generation"


def test_record_cost_accumulates(tmp_path: Path):
    run_dir = create_run_dir("accum-test", base_dir=tmp_path)
    record_cost(run_dir, "image_generation", 0.15, "img1", {})
    record_cost(run_dir, "image_generation", 0.15, "img2", {})
    record_cost(run_dir, "video_generation", 0.90, "vid1", {})
    metrics = load_metrics(run_dir)
    assert len(metrics["costs"]["items"]) == 3
    assert metrics["costs"]["total_usd"] == pytest.approx(1.20, abs=0.001)
    assert metrics["costs"]["by_category"]["image_generation"] == pytest.approx(0.30, abs=0.001)
    assert metrics["costs"]["by_category"]["video_generation"] == pytest.approx(0.90, abs=0.001)


# ---------------------------------------------------------------------------
# Metrics persistence
# ---------------------------------------------------------------------------


def test_metrics_save_load_roundtrip(tmp_path: Path):
    run_dir = create_run_dir("met-test", base_dir=tmp_path)
    metrics = load_metrics(run_dir)
    metrics["run_started_at"] = "2026-01-01T00:00:00"
    metrics["stages"]["images"] = {"started_at": "2026-01-01T00:00:00"}
    save_metrics(run_dir, metrics)
    loaded = load_metrics(run_dir)
    assert loaded["run_started_at"] == "2026-01-01T00:00:00"
    assert "images" in loaded["stages"]


def test_load_metrics_returns_default_when_missing(tmp_path: Path):
    metrics = load_metrics(tmp_path)
    assert metrics["run_started_at"] is None
    assert metrics["stages"] == {}
    assert metrics["costs"]["total_usd"] == 0.0
    assert metrics["costs"]["items"] == []
    assert metrics["costs"]["by_category"] == {}


def test_load_metrics_backfills_costs_keys(tmp_path: Path):
    """Metrics file missing costs sub-keys should be backfilled."""
    run_dir = create_run_dir("backfill-test", base_dir=tmp_path)
    # Write metrics with partial costs structure
    partial = {"stages": {}, "costs": {"total_usd": 1.0}}
    (run_dir / "run_metrics.json").write_text(json.dumps(partial))
    metrics = load_metrics(run_dir)
    assert metrics["costs"]["items"] == []
    assert metrics["costs"]["by_category"] == {}
    assert metrics["costs"]["total_usd"] == 1.0


# ---------------------------------------------------------------------------
# Stage timer start/complete with timing
# ---------------------------------------------------------------------------


def test_start_stage_timer_records_timestamps(tmp_path: Path):
    run_dir = create_run_dir("timer-test", base_dir=tmp_path)
    ts = start_stage_timer(run_dir, "images")
    assert isinstance(ts, float)
    metrics = load_metrics(run_dir)
    assert "images" in metrics["stages"]
    assert "started_at" in metrics["stages"]["images"]
    assert "start_timestamp" in metrics["stages"]["images"]


def test_stage_timer_end_to_end(tmp_path: Path):
    """Start timer, sleep briefly, mark complete — duration should be recorded."""
    run_dir = create_run_dir("e2e-timer", base_dir=tmp_path)
    start_stage_timer(run_dir, "videos")
    time.sleep(0.05)  # 50ms
    mark_stage_complete(run_dir, "videos")

    metrics = load_metrics(run_dir)
    stage = metrics["stages"]["videos"]
    assert "ended_at" in stage
    assert "end_timestamp" in stage
    assert "duration_seconds" in stage
    assert stage["duration_seconds"] >= 0.04  # at least ~40ms
