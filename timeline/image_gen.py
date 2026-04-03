"""Image generation adapter for timeline execution.

Translates timeline ImageSource objects into calls to generation/batch_img.py's
generate_single_image() function, with concurrency control and error handling.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import aiohttp

from generation import batch_img
from generation.batch_img import generate_single_image
from timeline.model import ImageDefaults, ImageSource, NodeResult

logger = logging.getLogger(__name__)


def _build_request(
    clip_id: str, source: ImageSource, run_dir: Path
) -> Dict[str, Any]:
    """Build the request dict expected by generate_single_image()."""
    output_dir = str(run_dir / "images")
    return {
        "prompt": source.prompt,
        "reference_images": source.reference_images,
        "filename": f"{clip_id}.{source.output_format}",
        "output_dir": output_dir,
        "config": {
            "aspect_ratio": source.aspect_ratio,
            "resolution": source.resolution,
            "output_format": source.output_format,
            "safety_filter_level": source.safety_filter_level,
        },
    }


async def _generate_one(
    session: aiohttp.ClientSession,
    clip_id: str,
    source: ImageSource,
    run_dir: Path,
    idx: int,
    semaphore: asyncio.Semaphore,
) -> Tuple[str, NodeResult | None]:
    """Generate a single image, returning (clip_id, result) or (clip_id, None) on failure."""
    async with semaphore:
        request = _build_request(clip_id, source, run_dir)

        # Save generation inputs before API call
        inputs_dir = run_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        input_record = {
            "type": "image",
            "model": "google/nano-banana-pro",
            "clip_id": clip_id,
            "prompt": source.prompt,
            "config": {
                "aspect_ratio": source.aspect_ratio,
                "resolution": source.resolution,
                "output_format": source.output_format,
                "safety_filter_level": source.safety_filter_level,
            },
            "reference_images": source.reference_images,
        }
        (inputs_dir / f"{clip_id}.json").write_text(json.dumps(input_record, indent=2))

        try:
            path, _log = await generate_single_image(
                session=session,
                default_messages=[],
                request=request,
                idx=idx,
                poll_sec=1.0,
                output_dir=Path(request["output_dir"]),
            )
            return clip_id, NodeResult(
                path=path,
                duration=None,
                media_type="image",
            )
        except Exception:
            logger.exception("Image generation failed for clip %s", clip_id)
            return clip_id, None


async def generate_images(
    sources: List[Tuple[str, ImageSource]],
    run_dir: Path,
    defaults: ImageDefaults,
    concurrency: int = 4,
) -> Dict[str, NodeResult]:
    """Generate images from ImageSource objects.

    Args:
        sources: List of (clip_id, ImageSource) tuples to generate.
        run_dir: Run directory; images are written to run_dir/images/.
        defaults: ImageDefaults to apply for unset source fields.
        concurrency: Max concurrent generation requests.

    Returns:
        Mapping of clip_id to NodeResult for successful generations.
    """
    if not sources:
        return {}

    # Ensure output directory exists
    images_dir = run_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(concurrency)
    token = os.environ.get("REPLICATE_API_TOKEN", "")
    if not token and not batch_img.MOCK_REPLICATE:
        raise EnvironmentError("REPLICATE_API_TOKEN not set")

    headers = {"Authorization": f"Bearer {token}"} if token else {}

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [
            _generate_one(session, clip_id, source, run_dir, idx, semaphore)
            for idx, (clip_id, source) in enumerate(sources)
        ]
        results_list = await asyncio.gather(*tasks)

    # Collect successful results
    results: Dict[str, NodeResult] = {}
    for clip_id, result in results_list:
        if result is not None:
            results[clip_id] = result

    return results
