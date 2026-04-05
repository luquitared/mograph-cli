"""Async client for Seedance 2.0 via MuAPI.

Provides text-to-video and image-to-video generation through the MuAPI
endpoint (https://api.muapi.ai). Uses aiohttp for async HTTP and polling.

Env:
  export MUAPI_API_KEY=...
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp

from shared.replicate_client import download_to, is_mock_mode

logger = logging.getLogger(__name__)

MUAPI_BASE_URL = "https://api.muapi.ai/api/v1"

# Mock mode fixture
MOCK_VIDEO_FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "mock_video.mp4"


def _get_muapi_headers() -> Dict[str, str]:
    """Build MuAPI auth headers from environment."""
    api_key = os.getenv("MUAPI_API_KEY", "")
    return {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }


async def _post_request(
    session: aiohttp.ClientSession,
    endpoint: str,
    payload: Dict,
) -> Dict:
    """POST a request to MuAPI and return the JSON response."""
    async with session.post(endpoint, json=payload, headers=_get_muapi_headers()) as resp:
        resp.raise_for_status()
        return await resp.json()


async def _poll_result(
    session: aiohttp.ClientSession,
    request_id: str,
    poll_sec: float = 5.0,
    timeout: float = 600.0,
) -> Dict:
    """Poll MuAPI for a generation result until completed or failed."""
    endpoint = f"{MUAPI_BASE_URL}/predictions/{request_id}/result"
    headers = _get_muapi_headers()
    elapsed = 0.0
    while elapsed < timeout:
        async with session.get(endpoint, headers=headers) as resp:
            result = await resp.json()
            if resp.status == 400:
                # 400 may indicate job still processing or a real error
                error = result.get("error", result.get("message", "unknown"))
                status = result.get("status", "")
                if status in ("processing", "pending", "queued"):
                    logger.debug("Seedance %s: 400 but status=%s, retrying...", request_id, status)
                    await asyncio.sleep(poll_sec)
                    elapsed += poll_sec
                    continue
                raise RuntimeError(f"Seedance poll failed (400): {error} — full response: {result}")
            resp.raise_for_status()

        status = result.get("status")
        if status == "completed":
            return result
        if status == "failed":
            error = result.get("error", "unknown error")
            raise RuntimeError(f"Seedance generation failed: {error}")

        logger.debug("Seedance %s status: %s, waiting %.0fs...", request_id, status, poll_sec)
        await asyncio.sleep(poll_sec)
        elapsed += poll_sec

    raise TimeoutError(f"Seedance generation timed out after {timeout}s for {request_id}")


async def text_to_video(
    session: aiohttp.ClientSession,
    prompt: str,
    aspect_ratio: str = "16:9",
    duration: int = 5,
    quality: str = "basic",
) -> str:
    """Submit a text-to-video generation and poll for result.

    Returns the URL of the generated video.
    """
    endpoint = f"{MUAPI_BASE_URL}/seedance-v2.0-t2v"
    payload = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
        "quality": quality,
    }

    resp = await _post_request(session, endpoint, payload)
    request_id = resp.get("request_id")
    if not request_id:
        raise RuntimeError(f"No request_id in Seedance T2V response: {resp}")

    logger.info("Seedance T2V submitted: %s", request_id)
    result = await _poll_result(session, request_id)
    url = result.get("url") or (result.get("outputs", [None])[0] if result.get("outputs") else None)
    if not url:
        raise RuntimeError(f"No URL in Seedance T2V result: {result}")
    return url


async def image_to_video(
    session: aiohttp.ClientSession,
    images_list: List[str],
    prompt: str = "",
    aspect_ratio: str = "16:9",
    duration: int = 5,
    quality: str = "basic",
) -> str:
    """Submit an image-to-video generation via Omni Reference endpoint and poll for result.

    Args:
        images_list: List of image URLs. Referenced in prompt as @image1, @image2, etc.
        prompt: Text prompt with @imageN references to guide generation.

    Returns the URL of the generated video.
    """
    endpoint = f"{MUAPI_BASE_URL}/seedance-2.0-omni-reference-480p"
    duration = max(8, min(15, duration))  # Omni Reference: 8-15s
    payload = {
        "prompt": prompt,
        "images_list": images_list,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
        "quality": quality,
    }

    resp = await _post_request(session, endpoint, payload)
    request_id = resp.get("request_id")
    if not request_id:
        raise RuntimeError(f"No request_id in Seedance Omni response: {resp}")

    logger.info("Seedance Omni submitted: %s", request_id)
    result = await _poll_result(session, request_id)
    url = result.get("url") or (result.get("outputs", [None])[0] if result.get("outputs") else None)
    if not url:
        raise RuntimeError(f"No URL in Seedance Omni result: {result}")
    return url


async def process_seedance_job(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    outdir: Path,
    prompt: str,
    idx: int,
    duration: int = 5,
    aspect_ratio: str = "16:9",
    quality: str = "basic",
    reference_image_urls: Optional[List[str]] = None,
    poll_sec: float = 5.0,
) -> Path:
    """Process a single Seedance video generation job.

    Routes to Omni Reference if reference images are provided,
    otherwise text-to-video. Images are referenced in the prompt as
    @image1, @image2, etc.

    Returns the path to the downloaded MP4 file.
    """
    async with sem:
        if is_mock_mode():
            dest = outdir / f"seedance-{idx:03d}.mp4"
            await download_to(session, f"file://{MOCK_VIDEO_FIXTURE}", dest)
            return dest

        images_list = list(reference_image_urls) if reference_image_urls else []

        if images_list:
            print(f"\U0001f680 [{idx}] Creating Seedance Omni prediction ({len(images_list)} images)...")
            video_url = await image_to_video(
                session=session,
                images_list=images_list,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                duration=duration,
                quality=quality,
            )
        else:
            print(f"\U0001f680 [{idx}] Creating Seedance 2.0 T2V prediction...")
            video_url = await text_to_video(
                session=session,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                duration=duration,
                quality=quality,
            )

        dest = outdir / f"seedance-{idx:03d}.mp4"
        print(f"\u2b07\ufe0f  [{idx}] Downloading Seedance result \u2192 {dest.name}")
        await download_to(session, video_url, dest)
        print(f"\u2705 [{idx}] Done: {dest}")
        return dest
