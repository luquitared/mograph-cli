"""Video generation adapter for timeline executor.

Translates timeline VideoSource objects into calls to generation/batch_vid.py's
process_job() function, giving per-job control over model selection and parameters.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp

from generation import batch_vid
from shared.media import probe_duration_async
from timeline.model import NodeResult, VideoDefaults, VideoSource

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model mapping: timeline canonical names → batch_vid model_kind
# ---------------------------------------------------------------------------

MODEL_KIND_MAP = {
    "seedance-2.0": "seedance",
    "seedance-2.0-fast": "seedance-fast",
}


# ---------------------------------------------------------------------------
# VideoJob dataclass
# ---------------------------------------------------------------------------

@dataclass
class VideoJob:
    """A single video generation job with resolved frame paths."""
    clip_id: str
    source: VideoSource
    first_frame_path: Optional[Path] = None
    last_frame_path: Optional[Path] = None
    reference_image_paths: List[Path] = field(default_factory=list)
    reference_video_paths: List[Path] = field(default_factory=list)
    reference_audio_paths: List[Path] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_model(source: VideoSource, defaults: VideoDefaults) -> str:
    """Resolve model name from source, falling back to defaults."""
    model = source.model or defaults.model
    return model


def _build_job_dict(job: VideoJob, defaults: VideoDefaults) -> Dict:
    """Build the job dict expected by batch_vid.process_job()."""
    source = job.source

    # Resolve defaults for unset fields
    duration = source.duration if source.duration is not None else defaults.duration
    aspect_ratio = source.aspect_ratio or defaults.aspect_ratio
    resolution = source.resolution or defaults.resolution
    generate_audio = source.generate_audio if source.generate_audio is not None else defaults.generate_audio

    result = {
        "prompt": source.prompt,
        "first_frame_image": str(job.first_frame_path) if job.first_frame_path else None,
        "last_frame_image": str(job.last_frame_path) if job.last_frame_path else None,
        "config": {
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "generate_audio": generate_audio,
            "negative_prompt": source.negative_prompt,
            "seed": source.seed,
            "quality": source.quality or "basic",
        },
    }
    if job.reference_image_paths:
        result["reference_images"] = [str(p) for p in job.reference_image_paths]
    if job.reference_video_paths:
        result["reference_videos"] = [str(p) for p in job.reference_video_paths]
    if job.reference_audio_paths:
        result["reference_audios"] = [str(p) for p in job.reference_audio_paths]
    return result


def _get_model_owner_name(model: str) -> tuple:
    """Map a timeline model name to (owner, name) via batch_vid."""
    model_kind = MODEL_KIND_MAP.get(model)
    if model_kind is None:
        logger.warning("Unknown model %r, falling back to 'fast'", model)
        model_kind = "fast"
    return batch_vid.get_model_for_kind(model_kind)


# ---------------------------------------------------------------------------
# Single job processor
# ---------------------------------------------------------------------------

async def _process_single_job(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    job: VideoJob,
    idx: int,
    outdir: Path,
    defaults: VideoDefaults,
    poll_sec: float,
) -> NodeResult:
    """Process a single VideoJob → NodeResult."""
    model = _resolve_model(job.source, defaults)
    model_owner, model_name = _get_model_owner_name(model)

    job_dict = _build_job_dict(job, defaults)

    # Save generation inputs before API call
    inputs_dir = outdir.parent / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    input_record = {
        "type": "video",
        "model": f"{model_owner}/{model_name}",
        "clip_id": job.clip_id,
        "prompt": job_dict["prompt"],
        "config": job_dict["config"],
        "first_frame_path": str(job.first_frame_path) if job.first_frame_path else None,
        "last_frame_path": str(job.last_frame_path) if job.last_frame_path else None,
    }
    (inputs_dir / f"{job.clip_id}.json").write_text(json.dumps(input_record, indent=2))

    # process_job writes output to outdir/{idx:03d}_*.mp4
    # We'll rename to clip_id.mp4 after
    result_path = await batch_vid.process_job(
        session=session,
        sem=sem,
        outdir=outdir,
        job=job_dict,
        idx=idx,
        poll_sec=poll_sec,
        model_owner=model_owner,
        model_name=model_name,
    )

    # Rename to clip_id.mp4 for deterministic output paths
    final_path = outdir / f"{job.clip_id}.mp4"
    if result_path != final_path:
        result_path.rename(final_path)

    # Probe duration
    duration = await probe_duration_async(final_path)

    return NodeResult(
        path=final_path,
        duration=duration,
        media_type="video",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_videos(
    jobs: List[VideoJob],
    run_dir: Path,
    defaults: VideoDefaults,
    concurrency: int = 3,
    poll_sec: float = 2.5,
) -> Dict[str, NodeResult]:
    """Generate videos from VideoSource objects with resolved frame paths.

    Args:
        jobs: List of VideoJob objects to generate.
        run_dir: Base run directory. Videos written to run_dir/videos/.
        defaults: Default video generation parameters.
        concurrency: Max concurrent Replicate predictions.
        poll_sec: Polling interval for prediction status.

    Returns:
        Mapping of clip ID → NodeResult(path, duration, media_type="video").
        Only includes successfully generated videos.
    """
    if not jobs:
        return {}

    outdir = run_dir / "videos"
    outdir.mkdir(parents=True, exist_ok=True)

    # Check for required API token — all models now use Replicate
    if not os.getenv("REPLICATE_API_TOKEN") and not batch_vid.MOCK_REPLICATE:
        raise EnvironmentError("REPLICATE_API_TOKEN not set.")

    token = os.getenv("REPLICATE_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    sem = asyncio.Semaphore(concurrency)

    results: Dict[str, NodeResult] = {}

    async with aiohttp.ClientSession(
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=None),
    ) as session:
        tasks = []
        for idx, job in enumerate(jobs, start=1):
            task = _process_single_job(
                session=session,
                sem=sem,
                job=job,
                idx=idx,
                outdir=outdir,
                defaults=defaults,
                poll_sec=poll_sec,
            )
            tasks.append((job.clip_id, task))

        # Gather all tasks, allowing individual failures
        coros = [t for _, t in tasks]
        task_results = await asyncio.gather(*coros, return_exceptions=True)

        for (clip_id, _), result in zip(tasks, task_results):
            if isinstance(result, Exception):
                logger.error("Video generation failed for clip %s: %s", clip_id, result)
            else:
                results[clip_id] = result

    succeeded = len(results)
    failed = len(jobs) - succeeded
    if failed:
        logger.warning("%d/%d video jobs failed", failed, len(jobs))
    logger.info("Generated %d videos successfully", succeeded)

    return results
