#!/usr/bin/env python3
"""
Replicate API functions for image and video generation.

Provides async functions for uploading files, starting predictions,
polling for completion, and downloading results.
"""
import asyncio
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import aiohttp

from shared.common import ensure_dir, guess_mime_image

REPLICATE_API = "https://api.replicate.com/v1"

import threading

# Thread-local storage for per-request state (thread-safe for Cloud Run's ThreadPoolExecutor)
_thread_local = threading.local()

# The async upload cache lock is still per-event-loop (OK — each thread has its own loop)
_upload_cache_lock: Optional[asyncio.Lock] = None


def _get_upload_cache() -> Dict[str, str]:
    """Get the thread-local upload cache."""
    if not hasattr(_thread_local, 'upload_cache'):
        _thread_local.upload_cache = {}
    return _thread_local.upload_cache


def set_mock_mode(enabled: bool) -> None:
    """Enable or disable mock mode for this thread/request."""
    _thread_local.mock_mode = enabled


def is_mock_mode() -> bool:
    """Check if mock mode is enabled for this thread/request."""
    return getattr(_thread_local, 'mock_mode', False)


def set_tts_test_mode(enabled: bool) -> None:
    """Enable TTS test mode for this thread/request."""
    _thread_local.tts_test_mode = enabled


def is_tts_test_mode() -> bool:
    """Check if TTS test mode is enabled for this thread/request."""
    return getattr(_thread_local, 'tts_test_mode', False)


def _get_upload_lock() -> asyncio.Lock:
    """Get or create the upload cache lock for the current event loop."""
    global _upload_cache_lock
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    # Create new lock if none exists or if we're in a different event loop
    if _upload_cache_lock is None:
        _upload_cache_lock = asyncio.Lock()
    else:
        # Check if lock is bound to current loop by trying to use it
        try:
            # If the lock's loop doesn't match, we need a new one
            if hasattr(_upload_cache_lock, '_loop') and _upload_cache_lock._loop is not loop:
                _upload_cache_lock = asyncio.Lock()
        except Exception:
            _upload_cache_lock = asyncio.Lock()

    return _upload_cache_lock


async def upload_file_to_replicate(
    session: aiohttp.ClientSession,
    file_path: Path,
    use_cache: bool = True,
) -> str:
    """Upload a local file to Replicate and return its URL.

    Uses a cache to avoid uploading the same file multiple times within a session.
    This significantly speeds up batch operations that reuse reference images.

    Args:
        session: aiohttp session
        file_path: Path to local file to upload
        use_cache: Whether to use the upload cache (default: True)

    Returns:
        URL string for the uploaded file
    """
    resolved_path = str(file_path.resolve())

    if is_mock_mode():
        return f"file://{file_path.resolve()}"

    # Check cache first
    if use_cache and resolved_path in _get_upload_cache():
        return _get_upload_cache()[resolved_path]

    # Use lock to prevent duplicate uploads of the same file
    async with _get_upload_lock():
        # Double-check after acquiring lock (another task may have uploaded)
        if use_cache and resolved_path in _get_upload_cache():
            return _get_upload_cache()[resolved_path]

        url = f"{REPLICATE_API}/files"
        mime = guess_mime_image(file_path)

        data = aiohttp.FormData()
        data.add_field(
            "content",
            file_path.read_bytes(),
            filename=file_path.name,
            content_type=mime,
        )

        async with session.post(url, data=data) as resp:
            txt = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Upload failed ({resp.status}): {txt}")
            payload = json.loads(txt)
            remote_url = payload.get("urls", {}).get("get")
            if not remote_url:
                raise RuntimeError(f"Unexpected upload response: {payload}")

            # Cache the result
            if use_cache:
                _get_upload_cache()[resolved_path] = remote_url

            return remote_url


async def start_prediction(
    session: aiohttp.ClientSession,
    owner: str,
    name: str,
    inputs: Dict[str, Any],
    mock_fixture: Optional[Path] = None,
) -> Dict[str, Any]:
    """Start a prediction on Replicate.

    Args:
        session: aiohttp session
        owner: Model owner (e.g., "bytedance")
        name: Model name (e.g., "seedance-2.0-fast")
        inputs: Input parameters for the model
        mock_fixture: Path to mock output file for testing (if provided, returns mock response)

    Returns:
        Prediction response dict with id, status, etc.
    """
    if mock_fixture:
        return {
            "id": f"mock-{os.urandom(4).hex()}",
            "status": "succeeded",
            "output": f"file://{mock_fixture.resolve()}",
        }

    url = f"{REPLICATE_API}/models/{owner}/{name}/predictions"

    async with session.post(url, json={"input": inputs}) as resp:
        if resp.status >= 400:
            text = await resp.text()
            raise RuntimeError(f"Prediction create failed ({resp.status}): {text}")
        return await resp.json()


async def poll_prediction(
    session: aiohttp.ClientSession,
    pred: Dict[str, Any],
    poll_sec: float = 2.5,
) -> Dict[str, Any]:
    """Poll a prediction until completion.

    Args:
        pred: Prediction dict from start_prediction()
        poll_sec: Seconds between poll attempts
        session: aiohttp session

    Returns:
        Completed prediction dict

    Raises:
        RuntimeError: If prediction fails
    """
    if is_mock_mode():
        return pred

    status = pred.get("status")
    get_url = pred.get("urls", {}).get("get")

    if not get_url:
        pred_id = pred.get("id")
        if not pred_id:
            raise RuntimeError(f"Missing prediction URL/ID in: {pred}")
        get_url = f"{REPLICATE_API}/predictions/{pred_id}"

    while status in {"starting", "processing", "queued"}:
        await asyncio.sleep(poll_sec)
        async with session.get(get_url) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(f"Polling failed ({resp.status}): {text}")
            pred = await resp.json()
            status = pred.get("status")

    if status != "succeeded":
        error_msg = pred.get("error", "")
        pred_id = pred.get("id", "unknown")
        raise RuntimeError(f"Prediction failed: {error_msg} ({pred_id})")

    return pred


async def download_to(
    session: aiohttp.ClientSession,
    url: str,
    dest: Path,
) -> Path:
    """Download a file from URL to local path.

    Args:
        session: aiohttp session
        url: URL to download from (supports file:// for mock mode)
        dest: Local destination path

    Returns:
        Path to downloaded file
    """
    # Handle file:// URLs (mock mode or local files)
    if url.startswith("file://"):
        src = Path(url[7:])
        ensure_dir(dest.parent)
        shutil.copy(src, dest)
        return dest

    async with session.get(url) as resp:
        if resp.status >= 400:
            text = await resp.text()
            raise RuntimeError(f"Download failed ({resp.status}): {text}")
        ensure_dir(dest.parent)
        with dest.open("wb") as f:
            async for chunk in resp.content.iter_chunked(1 << 20):
                f.write(chunk)
    return dest


# Error classification helpers

def is_content_moderation_error(error: Exception) -> bool:
    """Check if error is a content moderation/sensitive content flag."""
    error_str = str(error).lower()
    return (
        "flagged as sensitive" in error_str
        or "e005" in error_str
        or "sensitive content" in error_str
    )


def is_rate_limit_error(error: Exception) -> Tuple[bool, int]:
    """Check if error is a rate limit (429) error and extract retry delay.

    Returns:
        Tuple of (is_rate_limited, retry_after_seconds)
    """
    error_str = str(error)
    if "429" in error_str or "rate limit" in error_str.lower():
        match = re.search(r'retry_after["\s:]+(\d+)', error_str)
        if match:
            return True, int(match.group(1))
        return True, 15  # Default retry delay
    return False, 0
