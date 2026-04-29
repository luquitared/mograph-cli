#!/usr/bin/env python3
"""GPT Image 2 generation via Replicate (openai/gpt-image-2).

OpenAI's state-of-the-art image generation. Supports reference images for
editing/composing, aspect ratios 1:1 / 3:2 / 2:3, and webp/png/jpeg output.
Transparent backgrounds are not supported — use gpt-image-1.5 for those.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from shared.common import ensure_dir
from shared.replicate_client import (
    download_to,
    poll_prediction,
    start_prediction,
    upload_file_to_replicate,
)

logger = logging.getLogger(__name__)

MODEL_OWNER = "openai"
MODEL_NAME = "gpt-image-2"

VALID_ASPECT_RATIOS = {"1:1", "3:2", "2:3"}
VALID_OUTPUT_FORMATS = {"webp", "png", "jpeg"}
VALID_QUALITY = {"low", "medium", "high", "auto"}
VALID_BACKGROUND = {"auto", "opaque"}
VALID_MODERATION = {"auto", "low"}

MOCK_REPLICATE = False
MOCK_IMAGE_FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "mock_image.png"


async def generate_image(
    session: aiohttp.ClientSession,
    prompt: str,
    output_path: Path,
    aspect_ratio: str = "1:1",
    output_format: str = "webp",
    reference_images: Optional[List[Any]] = None,
    quality: Optional[str] = None,
    background: Optional[str] = None,
    output_compression: Optional[int] = None,
    moderation: Optional[str] = None,
    max_retries: int = 5,
    poll_sec: float = 2.0,
) -> Tuple[Path, List[Dict[str, Any]]]:
    """Generate a single image via Replicate's openai/gpt-image-2.

    Args:
        session: aiohttp session with Replicate auth headers.
        prompt: Text prompt for image generation.
        output_path: Where to write the output image.
        aspect_ratio: "1:1", "3:2", or "2:3".
        output_format: "webp" (default), "png", or "jpeg".
        reference_images: Optional list of local paths or URLs for editing/composing.
        quality: "low", "medium", "high", or "auto".
        background: "auto" or "opaque" (no transparency support).
        output_compression: 0-100% (applies to webp/jpeg).
        moderation: "auto" (default) or "low".
        max_retries: Max retry attempts on failure.
        poll_sec: Polling interval for Replicate predictions.

    Returns:
        Tuple of (output_path, attempt_log).
    """
    # Upload any local reference images and build the input_images URL list
    input_image_urls: List[str] = []
    for ref in reference_images or []:
        ref_str = str(ref)
        if ref_str.startswith(("http://", "https://")):
            input_image_urls.append(ref_str)
            continue
        p = Path(ref_str).expanduser().resolve()
        if p.exists():
            url = await upload_file_to_replicate(session, p)
            input_image_urls.append(url)

    inputs: Dict[str, Any] = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "output_format": output_format,
    }
    if input_image_urls:
        inputs["input_images"] = input_image_urls
    if quality:
        inputs["quality"] = quality
    if background:
        inputs["background"] = background
    if output_compression is not None:
        inputs["output_compression"] = output_compression
    if moderation:
        inputs["moderation"] = moderation
    # If OPENAI_API_KEY is in env, pass it through so Replicate bills the user's
    # OpenAI account directly instead of routing through Replicate's proxy.
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        inputs["openai_api_key"] = openai_key

    ensure_dir(output_path.parent)
    attempt_log: List[Dict[str, Any]] = []
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        entry = {"attempt": attempt, "success": False, "error": None}
        try:
            logger.info("[gpt-image-2] Generating image (attempt %d/%d)…", attempt, max_retries)
            pred = await start_prediction(
                session, MODEL_OWNER, MODEL_NAME, inputs,
                mock_fixture=MOCK_IMAGE_FIXTURE if MOCK_REPLICATE else None,
            )
            pred = await poll_prediction(session, pred, poll_sec=poll_sec)

            output = pred.get("output")
            # Output is an array of URIs per Replicate schema
            if isinstance(output, list):
                if not output:
                    raise RuntimeError(f"Empty output array in prediction: {pred}")
                output_url = output[0]
            elif isinstance(output, str):
                output_url = output
            else:
                raise RuntimeError(f"Unexpected output type in prediction: {pred}")

            await download_to(session, output_url, output_path)
            entry["success"] = True
            attempt_log.append(entry)
            logger.info("[gpt-image-2] Done: %s", output_path.name)
            return output_path, attempt_log

        except Exception as e:
            last_error = e
            entry["error"] = str(e)
            attempt_log.append(entry)
            logger.warning("[gpt-image-2] Attempt %d failed: %s", attempt, e)
            if attempt < max_retries:
                wait = min(2 ** attempt, 30)
                await asyncio.sleep(wait)

    raise RuntimeError(
        f"GPT Image 2 generation failed after {max_retries} attempts. Last error: {last_error}"
    )
