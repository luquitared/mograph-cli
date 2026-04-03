from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import json
import threading
from datetime import datetime, timezone


@dataclass
class CandidateInfo:
    index: int
    path: Path          # relative to run_dir
    prompt: str         # the prompt used for this candidate


@dataclass
class PendingSelection:
    id: str             # clip_id or asset_id
    type: str           # "clip" or "asset"
    media_type: str     # "image", "video", "audio"
    select: int         # how many to keep (from source.select, default 1)
    candidates: List[CandidateInfo] = field(default_factory=list)


@dataclass
class SelectionManifest:
    phase: str          # "images", "videos", "tts"
    pending_selections: List[PendingSelection] = field(default_factory=list)
    timestamp: str = ""


def manifest_to_dict(manifest: SelectionManifest) -> dict:
    """Serialize a SelectionManifest to a dict."""
    return {
        "phase": manifest.phase,
        "timestamp": manifest.timestamp,
        "pending_selections": [
            {
                "id": ps.id,
                "type": ps.type,
                "media_type": ps.media_type,
                "select": ps.select,
                "candidates": [
                    {
                        "index": c.index,
                        "path": str(c.path),
                        "prompt": c.prompt,
                    }
                    for c in ps.candidates
                ],
            }
            for ps in manifest.pending_selections
        ],
    }


def write_manifest(manifest: SelectionManifest, run_dir: Path) -> Path:
    """Write a selection manifest to run_dir/selection_manifest_{phase}.json."""
    if not manifest.timestamp:
        manifest.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    data = manifest_to_dict(manifest)

    path = run_dir / f"selection_manifest_{manifest.phase}.json"
    path.write_text(json.dumps(data, indent=2))
    return path


def read_manifest(run_dir: Path, phase: str) -> Optional[SelectionManifest]:
    """Read a selection manifest from disk. Returns None if not found."""
    path = run_dir / f"selection_manifest_{phase}.json"
    if not path.exists():
        return None

    data = json.loads(path.read_text())
    manifest = SelectionManifest(
        phase=data["phase"],
        timestamp=data.get("timestamp", ""),
        pending_selections=[
            PendingSelection(
                id=ps["id"],
                type=ps["type"],
                media_type=ps["media_type"],
                select=ps["select"],
                candidates=[
                    CandidateInfo(
                        index=c["index"],
                        path=Path(c["path"]),
                        prompt=c["prompt"],
                    )
                    for c in ps["candidates"]
                ],
            )
            for ps in data["pending_selections"]
        ],
    )
    return manifest


def validate_selections(
    manifest: SelectionManifest, selections: Dict[str, List[int]]
) -> List[str]:
    """Validate selections against a manifest. Returns list of error messages (empty = valid)."""
    errors: List[str] = []
    pending_by_id = {ps.id: ps for ps in manifest.pending_selections}

    # Check all required IDs are present
    for ps_id in pending_by_id:
        if ps_id not in selections:
            errors.append(f"Missing selection for '{ps_id}'")

    # Check each selection
    for sel_id, indices in selections.items():
        if sel_id not in pending_by_id:
            errors.append(f"Unknown selection ID '{sel_id}'")
            continue

        ps = pending_by_id[sel_id]

        if not isinstance(indices, list):
            errors.append(f"Selection for '{sel_id}' must be a list of indices")
            continue

        if len(indices) != ps.select:
            errors.append(
                f"Selection for '{sel_id}' requires {ps.select} choice(s), got {len(indices)}"
            )

        max_index = len(ps.candidates) - 1
        for idx in indices:
            if idx < 0 or idx > max_index:
                errors.append(
                    f"Index {idx} out of bounds for '{sel_id}' (0-{max_index})"
                )

        if len(indices) != len(set(indices)):
            errors.append(f"Duplicate indices in selection for '{sel_id}'")

    return errors


def write_selections(
    selections: Dict[str, List[int]], phase: str, run_dir: Path
) -> Path:
    """Write user selections to run_dir/selections_{phase}.json."""
    path = run_dir / f"selections_{phase}.json"
    if path.exists():
        raise ValueError(f"Selections already exist for phase '{phase}': {path}")
    path.write_text(json.dumps(selections, indent=2))
    return path


def read_selections(run_dir: Path, phase: str) -> Optional[Dict[str, List[int]]]:
    """Read selections file. Returns None if not found."""
    path = run_dir / f"selections_{phase}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def get_selected_paths(
    manifest: SelectionManifest, selections: Dict[str, List[int]]
) -> Dict[str, List[Path]]:
    """Return a dict mapping each ID to the list of selected candidate Paths."""
    pending_by_id = {ps.id: ps for ps in manifest.pending_selections}
    result: Dict[str, List[Path]] = {}

    for sel_id, indices in selections.items():
        ps = pending_by_id[sel_id]
        result[sel_id] = [ps.candidates[i].path for i in indices]

    return result


class ExplorationState:
    """Manages pause/resume for a single job's candidate selection."""

    def __init__(self) -> None:
        self._pause_event = threading.Event()
        self._pause_event.set()  # Start unpaused
        self._lock = threading.Lock()
        self._pending_phase: Optional[str] = None
        self._completed = False

    def pause(self, phase: str) -> None:
        """Pause execution for a selection phase."""
        with self._lock:
            self._pending_phase = phase
            self._pause_event.clear()

    def resume(self) -> None:
        """Resume execution after selection."""
        with self._lock:
            self._pending_phase = None
            self._pause_event.set()

    def wait_for_selection(self, timeout: Optional[float] = None) -> bool:
        """Block until resumed. Returns True if resumed, False if timed out."""
        return self._pause_event.wait(timeout=timeout)

    @property
    def completed(self) -> bool:
        with self._lock:
            return self._completed

    def mark_completed(self) -> None:
        with self._lock:
            self._completed = True
            self._pause_event.set()  # Unblock any waiters

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return not self._pause_event.is_set()

    @property
    def pending_phase(self) -> Optional[str]:
        with self._lock:
            return self._pending_phase

    def get_pause_state(self) -> tuple:
        """Returns (is_paused, pending_phase) atomically."""
        with self._lock:
            return (not self._pause_event.is_set(), self._pending_phase)
