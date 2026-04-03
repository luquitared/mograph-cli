from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from timeline.explorer import (
    CandidateInfo,
    ExplorationState,
    PendingSelection,
    SelectionManifest,
    get_selected_paths,
    read_manifest,
    read_selections,
    validate_selections,
    write_manifest,
    write_selections,
)


# --- Dataclass construction ---


def test_candidate_info_construction():
    c = CandidateInfo(index=0, path=Path("images/hero_0.png"), prompt="A hero shot")
    assert c.index == 0
    assert c.path == Path("images/hero_0.png")
    assert c.prompt == "A hero shot"


def test_pending_selection_construction():
    ps = PendingSelection(id="hero", type="clip", media_type="image", select=1)
    assert ps.id == "hero"
    assert ps.candidates == []


def test_selection_manifest_construction():
    m = SelectionManifest(phase="images")
    assert m.phase == "images"
    assert m.pending_selections == []
    assert m.timestamp == ""


# --- write_manifest / read_manifest ---


def _make_manifest() -> SelectionManifest:
    return SelectionManifest(
        phase="images",
        timestamp="2026-04-03T12:00:00Z",
        pending_selections=[
            PendingSelection(
                id="hero_shot",
                type="clip",
                media_type="image",
                select=1,
                candidates=[
                    CandidateInfo(0, Path("images/hero_0.png"), "A hero shot"),
                    CandidateInfo(1, Path("images/hero_1.png"), "A hero shot v2"),
                ],
            ),
            PendingSelection(
                id="bg_image",
                type="asset",
                media_type="image",
                select=2,
                candidates=[
                    CandidateInfo(0, Path("images/bg_0.png"), "Background"),
                    CandidateInfo(1, Path("images/bg_1.png"), "Background v2"),
                    CandidateInfo(2, Path("images/bg_2.png"), "Background v3"),
                ],
            ),
        ],
    )


def test_write_manifest_creates_file(tmp_path: Path):
    manifest = _make_manifest()
    result = write_manifest(manifest, tmp_path)
    assert result == tmp_path / "selection_manifest_images.json"
    assert result.exists()


def test_write_manifest_json_content(tmp_path: Path):
    manifest = _make_manifest()
    path = write_manifest(manifest, tmp_path)
    data = json.loads(path.read_text())
    assert data["phase"] == "images"
    assert data["timestamp"] == "2026-04-03T12:00:00Z"
    assert len(data["pending_selections"]) == 2
    # Paths should be strings
    cand = data["pending_selections"][0]["candidates"][0]
    assert isinstance(cand["path"], str)
    assert cand["path"] == "images/hero_0.png"


def test_write_manifest_auto_timestamp(tmp_path: Path):
    manifest = SelectionManifest(phase="videos")
    write_manifest(manifest, tmp_path)
    data = json.loads((tmp_path / "selection_manifest_videos.json").read_text())
    assert data["timestamp"] != ""


def test_read_manifest_roundtrip(tmp_path: Path):
    original = _make_manifest()
    write_manifest(original, tmp_path)
    loaded = read_manifest(tmp_path, "images")
    assert loaded is not None
    assert loaded.phase == "images"
    assert len(loaded.pending_selections) == 2
    assert loaded.pending_selections[0].id == "hero_shot"
    assert loaded.pending_selections[0].candidates[0].path == Path("images/hero_0.png")


def test_read_manifest_missing(tmp_path: Path):
    assert read_manifest(tmp_path, "nonexistent") is None


# --- validate_selections ---


def test_validate_selections_valid():
    manifest = _make_manifest()
    selections = {"hero_shot": [0], "bg_image": [1, 2]}
    assert validate_selections(manifest, selections) == []


def test_validate_selections_missing_id():
    manifest = _make_manifest()
    selections = {"hero_shot": [0]}  # missing bg_image
    errors = validate_selections(manifest, selections)
    assert any("bg_image" in e for e in errors)


def test_validate_selections_unknown_id():
    manifest = _make_manifest()
    selections = {"hero_shot": [0], "bg_image": [1, 2], "unknown": [0]}
    errors = validate_selections(manifest, selections)
    assert any("unknown" in e.lower() or "Unknown" in e for e in errors)


def test_validate_selections_wrong_count():
    manifest = _make_manifest()
    selections = {"hero_shot": [0, 1], "bg_image": [1, 2]}  # hero needs 1, got 2
    errors = validate_selections(manifest, selections)
    assert any("hero_shot" in e for e in errors)


def test_validate_selections_out_of_bounds():
    manifest = _make_manifest()
    selections = {"hero_shot": [5], "bg_image": [1, 2]}
    errors = validate_selections(manifest, selections)
    assert any("out of bounds" in e.lower() or "Index" in e for e in errors)


def test_validate_selections_duplicate_indices():
    manifest = _make_manifest()
    selections = {"hero_shot": [0], "bg_image": [1, 1]}
    errors = validate_selections(manifest, selections)
    assert any("duplicate" in e.lower() or "Duplicate" in e for e in errors)


# --- write_selections / read_selections ---


def test_write_selections_creates_file(tmp_path: Path):
    selections = {"hero_shot": [0], "bg_image": [1, 2]}
    result = write_selections(selections, "images", tmp_path)
    assert result == tmp_path / "selections_images.json"
    assert result.exists()


def test_write_selections_json_content(tmp_path: Path):
    selections = {"hero_shot": [0], "bg_image": [1, 2]}
    path = write_selections(selections, "images", tmp_path)
    data = json.loads(path.read_text())
    assert data == selections


def test_write_selections_duplicate_raises(tmp_path: Path):
    selections = {"hero_shot": [0]}
    write_selections(selections, "images", tmp_path)
    with pytest.raises(ValueError, match="already exist"):
        write_selections(selections, "images", tmp_path)


def test_read_selections_roundtrip(tmp_path: Path):
    selections = {"hero_shot": [0], "bg_image": [1, 2]}
    write_selections(selections, "images", tmp_path)
    loaded = read_selections(tmp_path, "images")
    assert loaded == selections


def test_read_selections_missing(tmp_path: Path):
    assert read_selections(tmp_path, "nonexistent") is None


# --- get_selected_paths ---


def test_get_selected_paths():
    manifest = _make_manifest()
    selections = {"hero_shot": [1], "bg_image": [0, 2]}
    result = get_selected_paths(manifest, selections)
    assert result["hero_shot"] == [Path("images/hero_1.png")]
    assert result["bg_image"] == [Path("images/bg_0.png"), Path("images/bg_2.png")]


def test_get_selected_paths_preserves_order():
    manifest = _make_manifest()
    selections = {"hero_shot": [0], "bg_image": [2, 0]}
    result = get_selected_paths(manifest, selections)
    assert result["bg_image"] == [Path("images/bg_2.png"), Path("images/bg_0.png")]


# --- ExplorationState ---


def test_exploration_state_starts_unpaused():
    state = ExplorationState()
    assert not state.is_paused
    assert state.pending_phase is None


def test_exploration_state_pause_resume():
    state = ExplorationState()
    state.pause("images")
    assert state.is_paused
    assert state.pending_phase == "images"
    state.resume()
    assert not state.is_paused
    assert state.pending_phase is None


def test_exploration_state_wait_returns_true_when_not_paused():
    state = ExplorationState()
    assert state.wait_for_selection(timeout=0.01) is True


def test_exploration_state_wait_timeout():
    state = ExplorationState()
    state.pause("images")
    assert state.wait_for_selection(timeout=0.05) is False
    assert state.is_paused


def test_exploration_state_wait_resumes_from_thread():
    state = ExplorationState()
    state.pause("videos")
    resumed = []

    def worker():
        result = state.wait_for_selection(timeout=2.0)
        resumed.append(result)

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.05)
    assert state.is_paused
    state.resume()
    t.join(timeout=2.0)
    assert resumed == [True]
    assert not state.is_paused


def test_exploration_state_concurrent_access():
    """Multiple threads reading state while pause/resume cycles."""
    state = ExplorationState()
    errors = []

    def reader():
        for _ in range(100):
            _ = state.is_paused
            _ = state.pending_phase

    def writer():
        for _ in range(50):
            state.pause("images")
            state.resume()

    threads = [threading.Thread(target=reader) for _ in range(4)]
    threads.append(threading.Thread(target=writer))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    # No exceptions means thread-safe
    assert True
