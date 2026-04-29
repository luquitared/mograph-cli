#!/usr/bin/env python3
"""Inspect the state of a project run directory.

Reads runs/<project>/state.json (written by scripts/run.py) and prints a
table of clips with their status, model, duration, and output path.

Usage:
    python scripts/runs_inspect.py <project-slug>
    python scripts/runs_inspect.py <project-slug> --failed-only
    python scripts/runs_inspect.py <project-slug> --json
    python scripts/runs_inspect.py --list                # list all projects
"""

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"


def list_projects() -> None:
    if not RUNS_DIR.exists():
        print("(no runs/ directory)")
        return
    found = []
    for d in sorted(RUNS_DIR.iterdir()):
        if not d.is_dir():
            continue
        state_path = d / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            n_total = len(state.get("clips", {}))
            n_done = sum(1 for c in state["clips"].values() if c.get("status") == "completed")
            last_run = state.get("last_run", "?")
            found.append((d.name, n_done, n_total, last_run))
    if not found:
        print("(no projects with state.json yet)")
        return
    print(f"{'PROJECT':<40} {'CLIPS':<10} {'LAST RUN'}")
    for name, done, total, last_run in found:
        print(f"{name:<40} {done}/{total:<8} {last_run}")


def inspect(project_slug: str, failed_only: bool, json_out: bool) -> int:
    project_dir = RUNS_DIR / project_slug
    state_path = project_dir / "state.json"
    if not state_path.exists():
        print(f"no state.json at {state_path}", file=sys.stderr)
        print("(run the pipeline via scripts/run.py to populate it)", file=sys.stderr)
        return 1

    state = json.loads(state_path.read_text())
    clips = state.get("clips", {})

    if failed_only:
        clips = {cid: c for cid, c in clips.items() if c.get("status") != "completed"}

    if json_out:
        print(json.dumps({**state, "clips": clips}, indent=2))
        return 0

    print(f"project:  {state['project']}")
    print(f"timeline: {state.get('timeline', '?')}")
    print(f"last run: {state.get('last_run', '?')}")
    if state.get("concat_path"):
        print(f"concat:   {project_dir / state['concat_path']}")
    print()

    if not clips:
        print("(no clips matching filter)")
        return 0

    width = max(len(cid) for cid in clips.keys())
    print(f"{'CLIP':<{width}}  {'STATUS':<10} {'MODEL':<22} {'DUR':<5} OUTPUT")
    for cid, c in clips.items():
        status = c.get("status", "?")
        model = (c.get("model") or "?")[:22]
        dur = c.get("duration", "?")
        out = c.get("output_path") or "—"
        marker = "✓" if status == "completed" else "✗"
        print(f"{cid:<{width}}  {marker} {status:<8} {model:<22} {str(dur):<5} {out}")

    n_total = len(state["clips"])
    n_done = sum(1 for c in state["clips"].values() if c.get("status") == "completed")
    print(f"\n{n_done}/{n_total} complete")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect a project run directory")
    ap.add_argument("project", nargs="?", help="Project slug (omit with --list)")
    ap.add_argument("--list", action="store_true", help="List all projects with state.json")
    ap.add_argument("--failed-only", action="store_true", help="Show only non-completed clips")
    ap.add_argument("--json", dest="json_out", action="store_true", help="Machine-readable output")
    args = ap.parse_args()

    if args.list:
        list_projects()
        return 0
    if not args.project:
        ap.print_help()
        return 2
    return inspect(args.project, args.failed_only, args.json_out)


if __name__ == "__main__":
    sys.exit(main())
