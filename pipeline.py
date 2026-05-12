#!/usr/bin/env python3
"""Timeline-based video generation pipeline.

The pipeline takes a timeline JSON file and produces narrated explainer videos
with motion graphics visuals.

Stages (controlled via --stage):
  images : generate images only
  videos : generate images + videos
  final  : full pipeline including narration and assembly
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

STAGE_MAP = {"images": 1, "videos": 2, "final": 3}


def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "video"


def _load_env_file(env_path: Path = Path(".env")) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        os.environ.setdefault(key, value)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for the pipeline CLI."""
    parser = argparse.ArgumentParser(description="Timeline-based video generation pipeline")
    parser.add_argument(
        "--stage",
        choices=list(STAGE_MAP.keys()),
        default="final",
        help="Highest stage to run (default: final)",
    )
    parser.add_argument(
        "--timeline-file",
        required=False,
        help="Path to timeline JSON file. See docs/reference/timeline/ for reference.",
    )
    # Deprecated flags — recognize them to give helpful migration messages
    parser.add_argument("--script-file", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--voice-file", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--tts-only", action="store_true", default=False, help=argparse.SUPPRESS)
    parser.add_argument("--timing-mode", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--output-root",
        default="runs",
        help="Directory where run outputs will be stored",
    )
    parser.add_argument(
        "--resume-dir",
        default=None,
        help="Existing run directory to resume from",
    )
    parser.add_argument(
        "--voice",
        default="Kore",
        help="Gemini TTS voice name (e.g., Kore, Puck, Charon, Aoede). Default: Kore.",
    )
    parser.add_argument(
        "--tts-model",
        default="gemini-2.5-flash-preview-tts",
        help="Gemini TTS model (default: gemini-2.5-flash-preview-tts). "
             "Use 'gemini-2.5-pro-preview-tts' for higher quality.",
    )
    parser.add_argument(
        "--tts-concurrency",
        type=int,
        default=5,
        help="Concurrent TTS requests (default: 5)",
    )
    parser.add_argument(
        "--video-concurrency",
        type=int,
        default=8,
        help="Concurrent video generations (default: 8)",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="List available Gemini TTS voices and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode: show execution plan without running",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Mock mode: use local test fixtures instead of calling APIs (for fast testing)",
    )
    parser.add_argument(
        "--upload-gcs",
        nargs="?",
        const="__env__",
        default=None,
        metavar="gs://bucket/prefix",
        help="Upload run outputs (mp4 + wav) to GCS and print signed URLs. "
             "Pass a gs:// URI, or pass the flag alone to use $GCS_OUTPUT_BUCKET from env.",
    )
    parser.add_argument(
        "--signed-url-days",
        type=int,
        default=7,
        help="Signed-URL expiry in days when --upload-gcs is set (default: 7).",
    )

    return parser


def _run_timeline(args: argparse.Namespace) -> Path:
    """Execute a timeline-format pipeline run."""
    from timeline.parser import parse_timeline
    from timeline.validator import validate
    from timeline.executor import execute_timeline
    from timeline.run_context import create_run_dir

    timeline_path = Path(args.timeline_file).expanduser().resolve()
    if not timeline_path.exists():
        raise SystemExit(f"Timeline file not found: {timeline_path}")

    # Parse
    timeline = parse_timeline(timeline_path)

    # Validate
    result = validate(timeline, timeline_dir=timeline_path.parent)
    if not result.is_valid:
        for err in result.errors:
            print(f"  {err.severity}: [{err.path}] {err.message}")
        raise SystemExit(f"Timeline validation failed with {len(result.errors)} error(s)")
    if result.warnings:
        for w in result.warnings:
            print(f"  WARNING: [{w.path}] {w.message}")

    # Dry run — show execution plan and exit
    if args.dry_run:
        from timeline.dag import build_dag, topological_sort
        dag = build_dag(timeline)
        levels = topological_sort(dag)
        total_nodes = sum(len(lvl) for lvl in levels)
        print(f"Timeline: {timeline.project.name}")
        print(f"  Clips: {sum(len(t.clips) for t in timeline.tracks)}")
        print(f"  DAG nodes: {total_nodes}")
        print(f"  Execution levels: {len(levels)}")
        print(f"  Stage: {args.stage}")
        print("Validation passed. Dry run complete.")
        return Path(".")

    # Setup run directory (or resume)
    if args.resume_dir:
        run_dir = Path(args.resume_dir).expanduser().resolve()
        if not run_dir.exists():
            raise SystemExit(f"Resume directory not found: {run_dir}")
    else:
        run_dir = create_run_dir(timeline.project.name, base_dir=Path(args.output_root))

    # Copy source timeline into run dir for reproducibility
    shutil.copy2(timeline_path, run_dir / "timeline.json")

    # Build concurrency dict
    concurrency = {}
    if hasattr(args, 'video_concurrency'):
        concurrency['video'] = args.video_concurrency

    # Execute
    run_result = execute_timeline(
        timeline=timeline,
        run_dir=run_dir,
        stage=args.stage,
        mock=args.mock,
        concurrency=concurrency,
        resume=bool(args.resume_dir),
        timeline_dir=timeline_path.parent,
    )

    # Check for pending exploration (candidate selection needed)
    if run_result.pending_exploration:
        phase = run_result.pending_exploration
        manifest_path = run_dir / f"selection_manifest_{phase}.json"
        next_stage = args.stage  # resume same stage to continue after selection

        print(f"\nExploration mode: candidates generated for {phase} phase.")
        print(f"Review candidates in: {run_dir}/")
        print(f"Selection manifest: {manifest_path}")
        print(f"\nTo continue, create a selections file and resume:")
        print(f"  python pipeline.py --timeline-file {timeline_path} --resume-dir {run_dir} --stage {next_stage}")
        return run_dir

    if not run_result.success:
        print("Timeline execution failed:")
        for err in run_result.errors:
            print(f"  {err}")
        raise SystemExit(1)

    print(f"Timeline execution complete. Output: {run_dir}")
    if run_result.outputs:
        for name, path in run_result.outputs.items():
            print(f"  {name}: {path}")

    if args.upload_gcs:
        _upload_run_to_gcs(run_dir, args.upload_gcs, args.signed_url_days)

    return run_dir


def _upload_run_to_gcs(run_dir: Path, uri_arg: str, expiry_days: int) -> None:
    """Upload mp4/wav outputs from a run directory to GCS and print signed URLs."""
    from datetime import timedelta
    from google.cloud import storage

    uri = os.environ.get("GCS_OUTPUT_BUCKET") if uri_arg == "__env__" else uri_arg
    if not uri or not uri.startswith("gs://"):
        print(f"error: --upload-gcs needs a gs:// URI (got {uri!r}). "
              "Set $GCS_OUTPUT_BUCKET or pass gs://bucket/prefix.", file=sys.stderr)
        return

    rest = uri[len("gs://"):].split("/", 1)
    bucket_name = rest[0]
    base_prefix = (rest[1] if len(rest) > 1 else "").rstrip("/")
    run_prefix = f"{base_prefix}/{run_dir.name}" if base_prefix else run_dir.name

    files = sorted(
        [p for p in run_dir.rglob("*") if p.is_file() and p.suffix.lower() in (".mp4", ".wav", ".mp3", ".m4a")]
    )
    if not files:
        print(f"warning: no media files found under {run_dir} to upload", file=sys.stderr)
        return

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    print(f"\nUploading {len(files)} file(s) → gs://{bucket_name}/{run_prefix}/")
    for src in files:
        rel = src.relative_to(run_dir).as_posix()
        blob_path = f"{run_prefix}/{rel}"
        blob = bucket.blob(blob_path)
        content_type = {
            ".mp4": "video/mp4", ".wav": "audio/wav",
            ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
        }.get(src.suffix.lower())
        blob.upload_from_filename(str(src), content_type=content_type)
        signed = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=expiry_days),
            method="GET",
        )
        size_mb = src.stat().st_size / 1_000_000
        print(f"  [{size_mb:5.1f} MB] {rel}")
        print(f"    {signed}")
    print(f"\nSigned URLs valid for {expiry_days} days.")


def main(args: Optional[argparse.Namespace] = None) -> Path:
    """Run the pipeline with given arguments. Returns the run directory path.

    Args:
        args: Parsed arguments. If None, parses from sys.argv.

    Returns:
        Path to the run directory.
    """
    if args is None:
        parser = build_arg_parser()
        args = parser.parse_args()

    # Check for deprecated flags and give migration guidance
    deprecated_flags = {
        "script_file": "--script-file has been removed. Use --timeline-file with the new timeline JSON format.\n  See docs/reference/timeline/ for migration guidance.",
        "voice_file": "--voice-file has been removed. Use file sources in timeline tracks instead.\n  See docs/workflows/narration-explainer/ for pre-recorded voice-over examples.",
        "tts_only": "--tts-only has been removed. Use --stage images to run TTS + image generation only.",
        "timing_mode": "--timing-mode has been removed. Use fit_to in timeline clips for timing control.\n  See docs/reference/timeline/format-reference.md for details.",
    }
    used_deprecated = []
    for attr, msg in deprecated_flags.items():
        if getattr(args, attr, None):
            used_deprecated.append(msg)
    if used_deprecated:
        print("error: Deprecated flags detected:\n", file=sys.stderr)
        for msg in used_deprecated:
            print(f"  {msg}\n", file=sys.stderr)
        sys.exit(1)

    # Require --timeline-file unless --list-voices is used
    if not getattr(args, "timeline_file", None) and not getattr(args, "list_voices", False):
        print("error: --timeline-file is required.\n", file=sys.stderr)
        print("Usage: python pipeline.py --timeline-file <path> [--stage <stage>]", file=sys.stderr)
        sys.exit(1)

    _load_env_file()

    # Handle --list-voices early exit
    if getattr(args, "list_voices", False):
        from tts.gemini_tts import GEMINI_VOICES as _VOICES
        print("Available Gemini TTS voices:")
        for v in _VOICES:
            print(f"  - {v}")
        return Path(".")

    return _run_timeline(args)


if __name__ == "__main__":
    main()
