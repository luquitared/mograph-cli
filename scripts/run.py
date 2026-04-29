#!/usr/bin/env python3
"""Project-aware wrapper around pipeline.py.

Keeps all work for a project in a single, stable directory:
    runs/<project-slug>/

vs. the pipeline's default of:
    runs/<Project Name>-<timestamp>/   (a new dir per invocation)

First run creates the dir and runs the pipeline. Subsequent runs use
--resume-dir against the same dir — the executor automatically skips
already-completed clips. After each run, writes a state.json summarizing
clip status (completed / missing) by inspecting the videos/ folder.

Usage:
    python scripts/run.py <timeline.json> [--project <slug>] [--stage final]

    # First run — creates runs/news-segment-full/
    python scripts/run.py docs/news-video/examples/news-segment-full.json

    # Resume — re-renders only failed/missing clips into the same dir
    python scripts/run.py docs/news-video/examples/news-segment-full.json

    # Force one clip to re-render (delete it and let resume regenerate)
    python scripts/run.py docs/news-video/examples/news-segment-full.json \
        --force-clip 04-pick3-patel-leaves
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "project"


def derive_project_slug(timeline_path: Path, override: str | None) -> str:
    if override:
        return slugify(override)
    timeline = json.loads(timeline_path.read_text())
    return slugify(timeline.get("project", {}).get("name", timeline_path.stem))


def update_state(project_dir: Path, timeline_path: Path) -> Dict[str, Any]:
    """Inspect the run dir + timeline, write state.json, return it."""
    timeline = json.loads(timeline_path.read_text())
    defaults = timeline.get("defaults", {})

    state: Dict[str, Any] = {
        "project": project_dir.name,
        "timeline": str(timeline_path.relative_to(PROJECT_ROOT)) if timeline_path.is_relative_to(PROJECT_ROOT) else str(timeline_path),
        "last_run": datetime.now(timezone.utc).isoformat(),
        "clips": {},
        "concat_path": None,
    }

    videos_dir = project_dir / "videos"
    for track in timeline.get("tracks", []):
        if track.get("type") != "video":
            continue
        for clip in track.get("clips", []):
            cid = clip.get("id")
            if not cid:
                continue
            source = clip.get("source", {})
            video_path = videos_dir / f"{cid}.mp4"
            state["clips"][cid] = {
                "status": "completed" if video_path.exists() else "missing",
                "output_path": str(video_path.relative_to(project_dir)) if video_path.exists() else None,
                "model": source.get("model") or defaults.get("video", {}).get("model"),
                "duration": clip.get("duration") or source.get("duration") or defaults.get("video", {}).get("duration"),
            }

    final_dir = project_dir / "final"
    if final_dir.exists():
        for name in ("video_polished.mp4", "video_concat.mp4"):
            f = final_dir / name
            if f.exists():
                state["concat_path"] = str(f.relative_to(project_dir))
                break

    (project_dir / "state.json").write_text(json.dumps(state, indent=2))
    return state


def main() -> int:
    ap = argparse.ArgumentParser(description="Project-aware wrapper around pipeline.py")
    ap.add_argument("timeline", help="Path to timeline.json")
    ap.add_argument("--project", help="Project slug (derived from timeline.project.name if omitted)")
    ap.add_argument("--stage", default="final", help="Pipeline stage: images / videos / final (default: final)")
    ap.add_argument("--force-clip", action="append", default=[],
                    help="Delete a clip's output before running so it gets re-rendered. Can be passed multiple times.")
    ap.add_argument("--force", action="store_true", help="Wipe all clip outputs and re-render everything")
    ap.add_argument("--no-validate", action="store_true", help="Skip timeline_validate pre-check")
    args = ap.parse_args()

    timeline_path = Path(args.timeline).resolve()
    if not timeline_path.is_file():
        print(f"timeline not found: {timeline_path}", file=sys.stderr)
        return 2

    project_slug = derive_project_slug(timeline_path, args.project)
    project_dir = PROJECT_ROOT / "runs" / project_slug
    project_dir.mkdir(parents=True, exist_ok=True)
    print(f"[run] project: {project_slug}", file=sys.stderr)
    print(f"[run] dir:     {project_dir}", file=sys.stderr)

    # Pre-validate (cheap, catches misconfigured timelines before paying for a pipeline run)
    if not args.no_validate:
        v = subprocess.run(
            ["python", str(PROJECT_ROOT / "scripts" / "timeline_validate.py"), str(timeline_path)],
            cwd=PROJECT_ROOT,
        )
        if v.returncode != 0:
            print("[run] timeline_validate failed — aborting (pass --no-validate to skip)", file=sys.stderr)
            return v.returncode

    # Force handling — wipe outputs so resume re-renders them
    videos_dir = project_dir / "videos"
    if args.force and videos_dir.exists():
        print(f"[run] --force: wiping {videos_dir}", file=sys.stderr)
        shutil.rmtree(videos_dir)
    elif args.force_clip:
        for cid in args.force_clip:
            f = videos_dir / f"{cid}.mp4"
            if f.exists():
                print(f"[run] --force-clip: removing {f.name}", file=sys.stderr)
                f.unlink()

    # If the timeline already lives inside the project_dir (e.g. user is
    # re-running against runs/<slug>/timeline.json), pipeline.py would try to
    # copy the file onto itself and raise SameFileError. Stage to a temp
    # location outside the run dir so the source/dest are distinct.
    pipeline_timeline_path = timeline_path
    try:
        timeline_path.relative_to(project_dir)
        staging_dir = PROJECT_ROOT / "runs" / ".staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        pipeline_timeline_path = staging_dir / f"{project_slug}.json"
        shutil.copy2(timeline_path, pipeline_timeline_path)
    except ValueError:
        pass  # timeline is outside project_dir — safe to use directly

    # Run pipeline with --resume-dir pointing at our stable project dir
    cmd = [
        "python", str(PROJECT_ROOT / "pipeline.py"),
        "--timeline-file", str(pipeline_timeline_path),
        "--resume-dir", str(project_dir),
        "--stage", args.stage,
    ]
    print(f"[run] exec: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    # Always refresh state.json (even if pipeline failed mid-run)
    state = update_state(project_dir, timeline_path)
    n_complete = sum(1 for c in state["clips"].values() if c["status"] == "completed")
    n_total = len(state["clips"])
    print(f"\n[run] {n_complete}/{n_total} clips complete", file=sys.stderr)
    print(f"[run] state: {project_dir / 'state.json'}", file=sys.stderr)
    if state["concat_path"]:
        print(f"[run] final: {project_dir / state['concat_path']}", file=sys.stderr)

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
