"""Still image-to-video adapter for timeline execution.

Converts static images into video clips of a specified duration using FFmpeg.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Union

from shared.media import image_to_video_async
from timeline.model import NodeResult, Ref, StillSource

logger = logging.getLogger(__name__)


def _resolve_image(
    image: Union[str, Ref],
    results: Dict[str, NodeResult],
) -> Path:
    """Resolve the image field to a concrete path."""
    if isinstance(image, Ref):
        ref_id = image.ref
        if ref_id not in results:
            raise ValueError(
                f"Still source references unresolved clip: {ref_id}"
            )
        return results[ref_id].path
    # String path — already resolved or absolute
    return Path(image)


async def generate_still_videos(
    sources: List[Tuple[str, StillSource]],
    run_dir: Path,
    results: Dict[str, NodeResult],
) -> Dict[str, NodeResult]:
    """Convert still images to video clips.

    Returns mapping of clip ID → NodeResult(path, duration, media_type="video").
    """
    if not sources:
        return {}

    sem = asyncio.Semaphore(20)

    async def _gen_one(clip_id: str, source: StillSource) -> Tuple[str, NodeResult]:
        async with sem:
            image_path = _resolve_image(source.image, results)
            if not image_path.exists():
                raise FileNotFoundError(
                    f"Still source image not found: {image_path}"
                )

            duration = source.duration
            dest = run_dir / "videos" / f"{clip_id}_still.mp4"

            await image_to_video_async(image_path, duration, dest)

            logger.info(
                "Generated still video %s: %s → %s (%.2fs)",
                clip_id, image_path, dest, duration,
            )
            return clip_id, NodeResult(
                path=dest,
                duration=duration,
                media_type="video",
            )

    tasks = [_gen_one(clip_id, source) for clip_id, source in sources]
    completed = await asyncio.gather(*tasks)

    return {clip_id: result for clip_id, result in completed}
