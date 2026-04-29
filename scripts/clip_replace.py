#!/usr/bin/env python3
"""Re-render a single clip in an existing project run.

Reads the cached timeline at runs/<project>/timeline.json (copied there by
the pipeline on the original run), applies optional inline overrides
(prompt / duration), deletes the existing clip output, runs the pipeline
to regenerate just that clip, and re-runs the final concat.

Usage:
    # Re-render with the existing prompt (e.g. retry after a transient failure)
    python scripts/clip_replace.py <project-slug> <clip-id>

    # Re-render with a new prompt (one-off; doesn't modify the source timeline)
    python scripts/clip_replace.py <project-slug> <clip-id> \
        --prompt "Anime news show. Maya: 'Updated line.' ..."

    # Override duration
    python scripts/clip_replace.py <project-slug> <clip-id> --duration 12
"""

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-render a single clip in an existing project")
    ap.add_argument("project", help="Project slug (e.g. news-segment-full)")
    ap.add_argument("clip_id", help="Clip id to re-render")
    ap.add_argument("--prompt", help="Inline prompt override (one-off; source timeline untouched)")
    ap.add_argument("--duration", type=int, help="Inline duration override")
    args = ap.parse_args()

    project_dir = PROJECT_ROOT / "runs" / args.project
    cached_timeline = project_dir / "timeline.json"
    if not cached_timeline.exists():
        print(f"no cached timeline at {cached_timeline}", file=sys.stderr)
        print("(this project has no recorded run — use scripts/run.py first)", file=sys.stderr)
        return 2

    timeline = json.loads(cached_timeline.read_text())

    # Locate the clip
    target_clip = None
    target_track_id = None
    for track in timeline.get("tracks", []):
        for clip in track.get("clips", []):
            if clip.get("id") == args.clip_id:
                target_clip = clip
                target_track_id = track.get("id")
                break
        if target_clip:
            break
    if not target_clip:
        print(f"clip id {args.clip_id!r} not found in timeline", file=sys.stderr)
        return 2

    # Build a single-clip timeline with overrides applied
    new_clip = copy.deepcopy(target_clip)
    if args.prompt:
        new_clip.setdefault("source", {})["prompt"] = args.prompt
    if args.duration:
        new_clip["duration"] = args.duration

    sub_timeline = {
        "version": timeline.get("version", 1),
        "project": timeline.get("project", {"name": args.project}),
        "defaults": timeline.get("defaults", {}),
        "tracks": [
            {
                "id": target_track_id or "visuals",
                "type": "video",
                "clips": [new_clip],
            }
        ],
        "output": timeline.get("output", {"format": "mp4"}),
    }

    sub_timeline_path = project_dir / f"_replace_{args.clip_id}.json"
    sub_timeline_path.write_text(json.dumps(sub_timeline, indent=2))

    # Delete the existing clip output so the pipeline re-renders it
    clip_video = project_dir / "videos" / f"{args.clip_id}.mp4"
    if clip_video.exists():
        print(f"[clip_replace] removing existing {clip_video.name}", file=sys.stderr)
        clip_video.unlink()

    # Render just the videos stage with the sub-timeline
    print(f"[clip_replace] rendering {args.clip_id} (overrides: {bool(args.prompt or args.duration)})", file=sys.stderr)
    r1 = subprocess.run(
        [
            "python", str(PROJECT_ROOT / "pipeline.py"),
            "--timeline-file", str(sub_timeline_path),
            "--resume-dir", str(project_dir),
            "--stage", "videos",
        ],
        cwd=PROJECT_ROOT,
    )
    if r1.returncode != 0 or not clip_video.exists():
        print(f"[clip_replace] re-render failed (clip output: {clip_video.exists()})", file=sys.stderr)
        return r1.returncode or 1

    # Re-concat using the original timeline (so all clips, in original order, get stitched)
    print(f"[clip_replace] re-running final concat", file=sys.stderr)
    r2 = subprocess.run(
        [
            "python", str(PROJECT_ROOT / "pipeline.py"),
            "--timeline-file", str(cached_timeline),
            "--resume-dir", str(project_dir),
            "--stage", "final",
        ],
        cwd=PROJECT_ROOT,
    )

    # Refresh state.json via run.py's logic
    subprocess.run(
        [
            "python", str(PROJECT_ROOT / "scripts" / "run.py"),
            str(cached_timeline),
            "--project", args.project,
            "--no-validate",
            "--stage", "final",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
    )

    print(f"[clip_replace] done. concat: {project_dir / 'final' / 'video_concat.mp4'}", file=sys.stderr)
    # Clean up the temporary sub-timeline
    sub_timeline_path.unlink(missing_ok=True)
    return r2.returncode


if __name__ == "__main__":
    sys.exit(main())
