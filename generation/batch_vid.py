#!/usr/bin/env python3
"""
Batch video generator for Google Veo 3.1 models via Replicate.

Supported Models:
  - google/veo-3.1      (quality): Full Veo 3.1, higher quality, supports 1080p
  - google/veo-3.1-fast (fast):    Veo 3.1 Fast, faster generation

Veo models use the image/last_frame API for frame-to-frame interpolation.

Jobs JSON shape (array of jobs):
  [
    {
      "prompt": "a cat steals a fish from a supermarket and escapes",
      "first_frame_image": "/abs/or/rel/path/to/start.png",   // alias: "start_image", "image"
      "last_frame_image": "/abs/or/rel/path/to/end.png",      // alias: "end_image", "last_frame"
      "config": {
        "duration": 8,                     // default: 6 seconds (4, 6, or 8 supported)
        "aspect_ratio": "16:9",            // default: 16:9 (also supports 9:16)
        "resolution": "720p",              // default: 720p (1080p for quality model)
        "generate_audio": true,            // default: true
        "negative_prompt": "...",          // optional
        "seed": 12345                      // optional
      }
    }
  ]

CLI:
  python batch_vid.py --jobs ./jobs.json --outdir ./downloads --max-concurrent 3 --model quality
  python batch_vid.py --jobs ./jobs.json --outdir ./downloads --model fast

Env:
  export REPLICATE_API_TOKEN=...
"""
import os
import json
import argparse
import asyncio
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from shared.common import ensure_dir, guess_mime_image, sanitize_filename
from shared.replicate_client import (
    is_content_moderation_error,
    is_rate_limit_error,
    upload_file_to_replicate,
    start_prediction,
    poll_prediction,
    download_to,
)

# Mock mode - set by pipeline when --mock flag is passed
MOCK_REPLICATE = False
MOCK_VIDEO_FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "mock_video.mp4"

# Model definitions
VEO_31_OWNER = "google"
VEO_31_NAME = "veo-3.1"
VEO_31_FAST_NAME = "veo-3.1-fast"

# Model tuples for selection
QUALITY_MODEL = (VEO_31_OWNER, VEO_31_NAME)        # Full Veo 3.1 - higher quality, reference_images API
FAST_MODEL = (VEO_31_OWNER, VEO_31_FAST_NAME)     # Veo 3.1 Fast - quicker, image/last_frame API

# Default model (Fast variant for backwards compatibility)
MODEL_OWNER = VEO_31_OWNER
MODEL_NAME = VEO_31_FAST_NAME


# -------------------- Config helpers --------------------

def pick_images(job: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Extract first and last frame image paths with alias support."""
    # Support multiple aliases for first frame
    first = (
        job.get("first_frame_image") or
        job.get("start_image") or
        job.get("image")
    )
    # Support multiple aliases for last frame
    last = (
        job.get("last_frame_image") or
        job.get("end_image") or
        job.get("last_frame")
    )
    return first, last


def coerce_config(job: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and normalize config parameters."""
    cfg = job.get("config", {})

    return {
        "duration": int(cfg.get("duration", 6)),
        "aspect_ratio": cfg.get("aspect_ratio", "16:9"),
        "resolution": cfg.get("resolution", "720p"),
        "generate_audio": bool(cfg.get("generate_audio", True)),
        "negative_prompt": cfg.get("negative_prompt"),
        "seed": cfg.get("seed"),
    }


# -------------------- Core job processing --------------------

async def process_job(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    outdir: Path,
    job: Dict[str, Any],
    idx: int,
    poll_sec: float,
    max_retries: int = 3,
    max_rate_limit_retries: int = 10,
    model_owner: str = MODEL_OWNER,
    model_name: str = MODEL_NAME,
) -> Path:
    """Process a single video generation job with retry logic for content moderation and rate limits.

    Supports both Veo 3.1 and Veo 3.1 Fast using the image/last_frame API for
    frame-to-frame interpolation. Both models accept the same input parameters.

    Rate limit retries use exponential backoff with jitter (up to max_rate_limit_retries).
    Content moderation retries use max_retries with a brief fixed delay.
    """
    async with sem:
        prompt: str = (job.get("prompt") or "").strip()
        if not prompt:
            raise ValueError(f"Job {idx}: 'prompt' is required.")

        # Get image paths
        first_path_str, last_path_str = pick_images(job)

        # Upload images if provided
        first_url = last_url = None
        if first_path_str:
            first_path = Path(first_path_str).expanduser().resolve()
            if not first_path.exists():
                raise FileNotFoundError(f"Job {idx}: first frame image not found: {first_path}")
            first_url = await upload_file_to_replicate(session, first_path)

        if last_path_str:
            last_path = Path(last_path_str).expanduser().resolve()
            if not last_path.exists():
                raise FileNotFoundError(f"Job {idx}: last frame image not found: {last_path}")
            last_url = await upload_file_to_replicate(session, last_path)

        # Get config
        config = coerce_config(job)

        # Retry loop with separate counters for rate limits vs content moderation
        last_error = None
        moderation_attempts = 0
        rate_limit_attempts = 0
        total_attempts = 0
        while True:
            total_attempts += 1
            try:
                # Build Replicate inputs
                inputs = {
                    "prompt": prompt,
                    "duration": config["duration"],
                    "aspect_ratio": config["aspect_ratio"],
                    "resolution": config["resolution"],
                    "generate_audio": config["generate_audio"],
                }

                # Add image inputs - both Veo 3.1 and Veo 3.1 Fast use the same API
                # for frame-to-frame interpolation (image + last_frame).
                if first_url:
                    inputs["image"] = first_url
                if last_url:
                    inputs["last_frame"] = last_url

                if config["negative_prompt"]:
                    inputs["negative_prompt"] = config["negative_prompt"]
                if config["seed"] is not None:
                    inputs["seed"] = config["seed"]

                attempt_label = f" (attempt {total_attempts})" if total_attempts > 1 else ""
                print(f"🚀 [{idx}] Creating prediction ({model_owner}/{model_name})…{attempt_label}")
                pred = await start_prediction(session, model_owner, model_name, inputs, mock_fixture=MOCK_VIDEO_FIXTURE if MOCK_REPLICATE else None)
                pred = await poll_prediction(session, pred, poll_sec=poll_sec)

                # Get output URL
                output_url = pred.get("output")
                if not output_url or not isinstance(output_url, str):
                    raise RuntimeError(f"Job {idx}: No output URL in prediction: {pred}")

                # Determine output filename
                base = sanitize_filename(prompt) or f"job-{idx}"
                filename = f"{base}-{model_owner}-{model_name}-{config['duration']}s.mp4"
                dest = outdir / filename

                print(f"⬇️  [{idx}] Downloading result → {dest.name}")
                await download_to(session, output_url, dest)
                print(f"✅ [{idx}] Done: {dest}")
                return dest

            except Exception as e:
                last_error = e

                # Check for rate limiting — use exponential backoff with jitter
                is_rate_limited, retry_delay = is_rate_limit_error(e)
                if is_rate_limited:
                    rate_limit_attempts += 1
                    if rate_limit_attempts < max_rate_limit_retries:
                        backoff = min(retry_delay * (2 ** (rate_limit_attempts - 1)), 60)
                        jitter = random.uniform(0, backoff * 0.5)
                        wait = backoff + jitter
                        print(f"⚠️  [{idx}] Rate limited, waiting {wait:.1f}s before retry (rate limit {rate_limit_attempts}/{max_rate_limit_retries})...")
                        await asyncio.sleep(wait)
                        continue
                    else:
                        print(f"❌ [{idx}] Failed after {rate_limit_attempts} rate limit retries")
                        raise

                if is_content_moderation_error(e):
                    moderation_attempts += 1
                    if moderation_attempts < max_retries:
                        print(f"⚠️  [{idx}] Content moderation flag detected, retrying ({moderation_attempts}/{max_retries})...")
                        await asyncio.sleep(1)
                        continue
                    else:
                        print(f"❌ [{idx}] Failed after {moderation_attempts} attempts due to content moderation")
                # Non-moderation/rate-limit errors or final retry - re-raise
                raise


# -------------------- Batch runner --------------------

def get_model_for_kind(model_kind: str) -> Tuple[str, str]:
    """Get model (owner, name) tuple based on model_kind selection."""
    if model_kind == "quality":
        return QUALITY_MODEL  # Full Veo 3.1
    elif model_kind == "fast":
        return FAST_MODEL     # Veo 3.1 Fast
    else:
        # Default to fast for backwards compatibility
        return FAST_MODEL


async def run_batch_async(
    jobs_path: Path,
    outdir: Path,
    max_concurrent: int = 3,
    poll_sec: float = 2.5,
    model_kind: str = "quality",
    max_retries: int = 3,
    max_rate_limit_retries: int = 10,
) -> List[Path]:
    """Run batch video generation with retry logic for content moderation and rate limits.

    Args:
        model_kind: "quality" for full Veo 3.1, "fast" for Veo 3.1 Fast
        max_retries: Max retries for content moderation errors (default 3)
        max_rate_limit_retries: Max retries for rate limit errors with exponential backoff (default 10)
    """
    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        raise EnvironmentError("REPLICATE_API_TOKEN not set.")

    ensure_dir(outdir)
    jobs = json.loads(Path(jobs_path).read_text())

    if not isinstance(jobs, list) or not jobs:
        raise ValueError("Jobs JSON must be a non-empty list of job objects.")

    # Select model based on model_kind
    model_owner, model_name = get_model_for_kind(model_kind)
    print(f"ℹ️  Using model: {model_owner}/{model_name} (kind: {model_kind})")

    headers = {"Authorization": f"Bearer {token}"}
    sem = asyncio.Semaphore(max_concurrent)

    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=None)) as session:
        tasks = [
            process_job(
                session, sem, outdir, job,
                idx=i + 1,
                poll_sec=poll_sec,
                max_retries=max_retries,
                max_rate_limit_retries=max_rate_limit_retries,
                model_owner=model_owner,
                model_name=model_name,
            )
            for i, job in enumerate(jobs)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Surface errors and collect successes
    paths: List[Path] = []
    had_errors = False
    for i, res in enumerate(results, start=1):
        if isinstance(res, Exception):
            had_errors = True
            print(f"❌ [{i}] ERROR: {res}")
        else:
            paths.append(res)

    if had_errors:
        print("⚠️  Some jobs failed. Successful outputs are still returned.")

    return paths


def main():
    parser = argparse.ArgumentParser(description="Concurrent Veo 3.1 batch video generator (Replicate).")
    parser.add_argument("--jobs", required=True, help="Path to JSON array of jobs.")
    parser.add_argument("--outdir", required=True, help="Folder where generated videos should be saved.")
    parser.add_argument("--max-concurrent", type=int, default=3, help="Max concurrent predictions (default: 3).")
    parser.add_argument("--poll-sec", type=float, default=2.5, help="Polling interval in seconds (default: 2.5).")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries for content moderation errors (default: 3).")
    parser.add_argument("--max-rate-limit-retries", type=int, default=10, help="Max retries for rate limit errors with exponential backoff (default: 10).")
    parser.add_argument(
        "--model",
        choices=["quality", "fast"],
        default="quality",
        help="Model to use: 'quality' for Veo 3.1, 'fast' for Veo 3.1 Fast. Default: quality",
    )
    args = parser.parse_args()

    jobs_path = Path(args.jobs).expanduser().resolve()
    outdir = Path(args.outdir).expanduser().resolve()

    model_owner, model_name = get_model_for_kind(args.model)
    print(f"ℹ️  Using Google {model_name} ({model_owner}/{model_name})")
    print(f"ℹ️  Defaults: duration=6s, aspect_ratio=16:9, resolution=720p, generate_audio=true")
    if args.model == "quality":
        print(f"ℹ️  Quality mode: supports 1080p resolution, uses reference_images API")
    print(f"ℹ️  Content moderation retry: enabled (max {args.max_retries} attempts)")
    print(f"ℹ️  Rate limit retry: enabled (max {args.max_rate_limit_retries} attempts, exponential backoff)")

    paths = asyncio.run(run_batch_async(
        jobs_path=jobs_path,
        outdir=outdir,
        max_concurrent=args.max_concurrent,
        poll_sec=args.poll_sec,
        model_kind=args.model,
        max_retries=args.max_retries,
        max_rate_limit_retries=args.max_rate_limit_retries,
    ))

    # Print JSON list of output filepaths
    print(json.dumps([str(p) for p in paths], indent=2))


if __name__ == "__main__":
    main()
