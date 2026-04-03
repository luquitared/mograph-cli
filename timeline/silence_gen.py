"""Silence generation adapter for timeline execution.

Generates silent audio clips of specified durations using FFmpeg.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from shared.media import generate_silence
from timeline.model import NodeResult, SilenceSource

logger = logging.getLogger(__name__)


async def generate_silence_clips(
    sources: List[Tuple[str, SilenceSource]],
    run_dir: Path,
) -> Dict[str, NodeResult]:
    """Generate silence audio files.

    Returns mapping of clip ID → NodeResult(path, duration, media_type="audio").
    """
    if not sources:
        return {}

    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(20)

    async def _gen_one(clip_id: str, source: SilenceSource) -> Tuple[str, NodeResult]:
        async with sem:
            duration = max(source.duration, 0.1)
            dest = run_dir / "audio" / f"{clip_id}_silence.wav"
            await loop.run_in_executor(None, generate_silence, duration, dest)
            logger.info("Generated silence %s: %.2fs → %s", clip_id, duration, dest)
            return clip_id, NodeResult(
                path=dest,
                duration=duration,
                media_type="audio",
            )

    tasks = [_gen_one(clip_id, source) for clip_id, source in sources]
    completed = await asyncio.gather(*tasks)

    return {clip_id: result for clip_id, result in completed}
