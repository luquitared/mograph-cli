#!/usr/bin/env python3
"""Scan pipeline run directories and produce a generation log for E2E test review.

Usage:
    python tests/e2e_log.py                     # scan ./runs, write to tests/e2e_generation_log.jsonl
    python tests/e2e_log.py --runs-dir runs     # explicit runs directory
    python tests/e2e_log.py --filter 01_text    # only include runs whose script path contains this string
    python tests/e2e_log.py --latest 5          # only the 5 most recent runs
"""

import argparse
import json
from pathlib import Path


def scan_run(run_dir: Path) -> dict | None:
    """Extract a log entry from a single run directory."""
    config_path = run_dir / "run_config.json"
    metrics_path = run_dir / "run_metrics.json"

    if not config_path.exists():
        return None

    config = json.loads(config_path.read_text())
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}

    # Identify the source script
    prompt_field = config.get("prompt", "")
    script_file = None
    if prompt_field.startswith("Script: "):
        script_file = prompt_field.removeprefix("Script: ")

    # Detect mock mode: mock runs have $0 cost and fixture paths in outputs
    is_mock = False
    images_dir = run_dir / "images"
    if images_dir.exists():
        for img in images_dir.glob("*.png"):
            # Mock images are copies of the fixture — all identical size
            if img.stat().st_size > 0:
                break
        # Check if any video output references a fixture path
        for vid in (run_dir / "videos").glob("*.mp4") if (run_dir / "videos").exists() else []:
            pass

    # If total cost is exactly 0 and stages completed, likely mock
    total_cost = metrics.get("costs", {}).get("total_usd", 0.0)
    completed_stages = config.get("completed_stages", [])
    if completed_stages and total_cost == 0.0:
        is_mock = True

    # Collect per-scene outputs
    scenes = []
    for img in sorted(images_dir.glob("scene*_*.png")) if images_dir.exists() else []:
        name = img.stem
        scene_num = int(name.split("_")[0].removeprefix("scene"))
        concept = "_".join(name.split("_")[3:])  # after sceneNN_vN_type_

        scene_entry = {
            "scene": scene_num,
            "concept": concept,
            "image": str(img.relative_to(run_dir.parent)),
        }

        # Find matching video
        videos_dir = run_dir / "videos"
        if videos_dir.exists():
            matching_vids = list(videos_dir.glob(f"{name}*.*"))
            if not matching_vids:
                # Try without extension variations
                matching_vids = list(videos_dir.glob(f"scene{scene_num:02d}*.*"))
            for vid in matching_vids:
                if vid.suffix in (".mp4", ".webm"):
                    scene_entry["video"] = str(vid.relative_to(run_dir.parent))
                    break

        scenes.append(scene_entry)

    # Find final video
    final_video = None
    for name in ("final.mp4", "final_sfx.mp4", "final_images_only.mp4"):
        candidate = run_dir / name
        if candidate.exists():
            final_video = str(candidate.relative_to(run_dir.parent))
            break

    # Timing
    total_duration = metrics.get("total_duration_seconds")

    return {
        "timestamp": metrics.get("run_started_at", ""),
        "script": script_file,
        "run_dir": str(run_dir.relative_to(run_dir.parent)),
        "mock": is_mock,
        "completed_stages": completed_stages,
        "scenes": scenes,
        "final_video": final_video,
        "cost_usd": round(total_cost, 4),
        "duration_sec": round(total_duration, 1) if total_duration else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate E2E test run log")
    parser.add_argument("--runs-dir", default="runs", help="Directory containing run outputs")
    parser.add_argument("--output", default="tests/e2e_generation_log.jsonl", help="Output log file")
    parser.add_argument("--filter", default=None, help="Only include runs whose script path contains this string")
    parser.add_argument("--latest", type=int, default=None, help="Only include the N most recent runs")
    args = parser.parse_args()

    runs_path = Path(args.runs_dir)
    if not runs_path.exists():
        print(f"Runs directory not found: {runs_path}")
        return

    # Collect all valid run directories (sorted by modification time, newest first)
    entries = []
    for run_dir in sorted(runs_path.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not run_dir.is_dir():
            continue
        entry = scan_run(run_dir)
        if entry is None:
            continue
        if args.filter and (not entry["script"] or args.filter not in entry["script"]):
            continue
        entries.append(entry)

    if args.latest:
        entries = entries[: args.latest]

    # Write JSONL
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    print(f"Wrote {len(entries)} entries to {output_path}")

    # Print summary table
    if entries:
        print(f"\n{'Script':<45} {'Mock':<6} {'Stages':<20} {'Cost':>8} {'Time':>10}")
        print("-" * 95)
        for e in entries:
            script_name = Path(e["script"]).name if e["script"] else "(unknown)"
            stages = ", ".join(e["completed_stages"]) if e["completed_stages"] else "-"
            cost = f"${e['cost_usd']:.2f}" if e["cost_usd"] else "-"
            duration = f"{e['duration_sec']:.0f}s" if e["duration_sec"] else "-"
            mock = "yes" if e["mock"] else "no"
            print(f"{script_name:<45} {mock:<6} {stages:<20} {cost:>8} {duration:>10}")


if __name__ == "__main__":
    main()
