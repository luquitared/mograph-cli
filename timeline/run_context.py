"""Run directory setup and persistence for timeline execution.

Provides helpers for creating run directories, tracking stage completion,
recording costs, and persisting metrics — extracted from pipeline.py patterns.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from shared.costs import IMAGE_COST_USD, VIDEO_SECOND_COST_USD, TTS_COST_USD

METRICS_FILENAME = "run_metrics.json"
CONFIG_FILENAME = "run_config.json"

RUN_SUBDIRS = [
    "images",
    "videos",
    "audio",
    "extracted_frames",
    "videos_adjusted",
    "videos_with_audio",
    "final",
    "downloads",
    "segments",
]


# ---------------------------------------------------------------------------
# Run directory creation
# ---------------------------------------------------------------------------


def create_run_dir(project_name: str, base_dir: Path = Path("runs")) -> Path:
    """Create a timestamped run directory with all required subdirectories."""
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', project_name)
    if not safe_name:
        safe_name = "untitled"
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = base_dir / f"{safe_name}-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    for subdir in RUN_SUBDIRS:
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)
    return run_dir


# ---------------------------------------------------------------------------
# Timeline copy
# ---------------------------------------------------------------------------


def save_timeline_copy(run_dir: Path, timeline_dict: dict) -> Path:
    """Save original timeline JSON into the run directory."""
    path = run_dir / "timeline.json"
    path.write_text(json.dumps(timeline_dict, indent=2))
    return path


# ---------------------------------------------------------------------------
# Run config (completed stages tracking)
# ---------------------------------------------------------------------------


def save_run_config(run_dir: Path, config: dict) -> None:
    """Save run configuration to run_config.json."""
    (run_dir / CONFIG_FILENAME).write_text(json.dumps(config, indent=2))


def load_run_config(run_dir: Path) -> dict:
    """Load run configuration, returning empty dict if not found."""
    cfg_path = run_dir / CONFIG_FILENAME
    if cfg_path.exists():
        return json.loads(cfg_path.read_text())
    return {}


# ---------------------------------------------------------------------------
# Stage completion
# ---------------------------------------------------------------------------


def mark_stage_complete(run_dir: Path, stage: str) -> None:
    """Mark a stage as completed and record end timing."""
    config = load_run_config(run_dir)
    config.setdefault("completed_stages", [])
    if stage not in config["completed_stages"]:
        config["completed_stages"].append(stage)
    save_run_config(run_dir, config)

    # Record stage end timing if we have a start timestamp
    metrics = load_metrics(run_dir)
    if stage in metrics.get("stages", {}) and "start_timestamp" in metrics["stages"][stage]:
        start_time = metrics["stages"][stage]["start_timestamp"]
        end_time = time.time()
        duration = end_time - start_time

        metrics["stages"][stage]["ended_at"] = datetime.now().isoformat()
        metrics["stages"][stage]["end_timestamp"] = end_time
        metrics["stages"][stage]["duration_seconds"] = round(duration, 2)
        save_metrics(run_dir, metrics)


def is_stage_complete(run_dir: Path, stage: str) -> bool:
    """Check if a stage has been completed."""
    config = load_run_config(run_dir)
    return stage in config.get("completed_stages", [])


# ---------------------------------------------------------------------------
# Metrics persistence
# ---------------------------------------------------------------------------


def _default_metrics() -> Dict[str, Any]:
    """Return a fresh metrics structure."""
    return {
        "run_started_at": None,
        "run_ended_at": None,
        "total_duration_seconds": None,
        "stages": {},
        "costs": {
            "total_usd": 0.0,
            "items": [],
            "by_category": {},
        },
    }


def load_metrics(run_dir: Path) -> Dict[str, Any]:
    """Load existing metrics or return empty structure."""
    metrics_path = run_dir / METRICS_FILENAME
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text())
        if "costs" not in metrics:
            metrics["costs"] = {"total_usd": 0.0, "items": [], "by_category": {}}
        else:
            metrics["costs"].setdefault("items", [])
            metrics["costs"].setdefault("by_category", {})
            metrics["costs"].setdefault("total_usd", 0.0)
        return metrics
    return _default_metrics()


def save_metrics(run_dir: Path, metrics: Dict[str, Any]) -> None:
    """Save metrics to JSON file."""
    (run_dir / METRICS_FILENAME).write_text(json.dumps(metrics, indent=2))


# ---------------------------------------------------------------------------
# Stage timing
# ---------------------------------------------------------------------------


def start_stage_timer(run_dir: Path, stage: str) -> float:
    """Record start time for a stage. Returns the start timestamp."""
    start_time = time.time()
    metrics = load_metrics(run_dir)
    if stage not in metrics["stages"]:
        metrics["stages"][stage] = {}
    metrics["stages"][stage]["started_at"] = datetime.now().isoformat()
    metrics["stages"][stage]["start_timestamp"] = start_time
    save_metrics(run_dir, metrics)
    return start_time


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------


def record_cost(
    run_dir: Path,
    category: str,
    amount_usd: float,
    label: str,
    details: dict,
) -> None:
    """Record a cost entry in run metrics."""
    metrics = load_metrics(run_dir)

    entry = {
        "category": category,
        "amount_usd": round(float(amount_usd), 4),
        "label": label,
        "details": details,
        "timestamp": datetime.now().isoformat(),
    }
    metrics["costs"]["items"].append(entry)
    metrics["costs"]["total_usd"] = round(
        metrics["costs"]["total_usd"] + float(amount_usd), 4
    )
    metrics["costs"]["by_category"][category] = round(
        metrics["costs"]["by_category"].get(category, 0.0) + float(amount_usd), 4
    )
    save_metrics(run_dir, metrics)
