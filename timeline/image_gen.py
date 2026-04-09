"""Image generation adapter for timeline execution.

Translates timeline ImageSource objects into calls to the appropriate backend:
- nano-banana-pro: Replicate API (generation/batch_img.py)
- nano-banana-2:   Gemini API direct (generation/nano_banana2.py) — burst mode
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import aiohttp

from generation import batch_img
from generation import nano_banana2
from generation.batch_img import generate_single_image
from generation.nano_banana2 import generate_image as generate_image_nb2
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


def _save_input_record(clip_id: str, source: ImageSource, run_dir: Path) -> None:
    """Save generation input metadata for reproducibility."""
    inputs_dir = run_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    input_record = {
        "type": "image",
        "model": source.model,
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


async def _generate_one_replicate(
    session: aiohttp.ClientSession,
    clip_id: str,
    source: ImageSource,
    run_dir: Path,
    idx: int,
    semaphore: asyncio.Semaphore,
) -> Tuple[str, NodeResult | None]:
    """Generate via Replicate (nano-banana-pro)."""
    async with semaphore:
        request = _build_request(clip_id, source, run_dir)
        _save_input_record(clip_id, source, run_dir)

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


async def _generate_one_nb2(
    session: aiohttp.ClientSession,
    clip_id: str,
    source: ImageSource,
    run_dir: Path,
    idx: int,
    semaphore: asyncio.Semaphore,
) -> Tuple[str, NodeResult | None]:
    """Generate via Gemini API direct (nano-banana-2 burst mode)."""
    async with semaphore:
        _save_input_record(clip_id, source, run_dir)
        output_path = run_dir / "images" / f"{clip_id}.{source.output_format}"

        try:
            path, _log = await generate_image_nb2(
                session=session,
                prompt=source.prompt,
                output_path=output_path,
                aspect_ratio=source.aspect_ratio,
                resolution=source.resolution,
                output_format=source.output_format,
                reference_images=source.reference_images or None,
            )
            return clip_id, NodeResult(
                path=path,
                duration=None,
                media_type="image",
            )
        except Exception:
            logger.exception("Image generation (nano-banana-2) failed for clip %s", clip_id)
            return clip_id, None


async def generate_images(
    sources: List[Tuple[str, ImageSource]],
    run_dir: Path,
    defaults: ImageDefaults,
    concurrency: int = 4,
) -> Dict[str, NodeResult]:
    """Generate images from ImageSource objects.

    Routes to the appropriate backend based on source.model:
    - "nano-banana-pro": Replicate API (requires REPLICATE_API_TOKEN)
    - "nano-banana-2":   Gemini API direct (requires GOOGLE_API_KEY)

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

    # Split sources by model
    replicate_sources = [(cid, src) for cid, src in sources if src.model != "nano-banana-2"]
    nb2_sources = [(cid, src) for cid, src in sources if src.model == "nano-banana-2"]

    semaphore = asyncio.Semaphore(concurrency)
    tasks = []

    # Replicate path (nano-banana-pro)
    if replicate_sources:
        token = os.environ.get("REPLICATE_API_TOKEN", "")
        if not token and not batch_img.MOCK_REPLICATE:
            raise EnvironmentError("REPLICATE_API_TOKEN not set")

        headers = {"Authorization": f"Bearer {token}"} if token else {}
        rep_session = aiohttp.ClientSession(headers=headers)

        for idx, (clip_id, source) in enumerate(replicate_sources):
            tasks.append(("replicate", rep_session, clip_id, source, idx))
    else:
        rep_session = None

    # Gemini direct path (nano-banana-2)
    if nb2_sources:
        nb2_session = aiohttp.ClientSession()
        for idx, (clip_id, source) in enumerate(nb2_sources):
            tasks.append(("nb2", nb2_session, clip_id, source, idx))
    else:
        nb2_session = None

    # Build coroutines
    coros = []
    for backend, session, clip_id, source, idx in tasks:
        if backend == "replicate":
            coros.append(_generate_one_replicate(session, clip_id, source, run_dir, idx, semaphore))
        else:
            coros.append(_generate_one_nb2(session, clip_id, source, run_dir, idx, semaphore))

    try:
        results_list = await asyncio.gather(*coros)
    finally:
        if rep_session:
            await rep_session.close()
        if nb2_session:
            await nb2_session.close()

    # Collect successful results
    results: Dict[str, NodeResult] = {}
    for clip_id, result in results_list:
        if result is not None:
            results[clip_id] = result

    return results
