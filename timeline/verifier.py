"""Post-generation verification for images and videos.

Uses Gemini vision to check whether generated media adheres to the
generation prompt. Returns a structured result with pass/fail, reasoning,
and attempt count.

Verification is opt-in via the ``verify`` field on image/video sources:
- ``verify: true`` → default prompt adherence check against source.prompt
- ``verify: "custom criteria"`` → custom criteria passed to the model
- ``verify: false`` or omitted → no verification
"""

import asyncio
import base64
import json
import logging
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .model import ImageSource, NodeResult, Source, VerificationEntry, VideoSource

logger = logging.getLogger(__name__)

# Default verification model
DEFAULT_VERIFY_MODEL = "gemini-2.5-flash"
DEFAULT_MAX_ATTEMPTS = 3


def should_verify(source: Source) -> bool:
    """Check if a source has verification enabled."""
    verify = getattr(source, "verify", None)
    return verify is not None and verify is not False


def _build_verify_prompt(source: Source) -> str:
    """Build the verification prompt from source config.

    If verify is True, checks adherence to the generation prompt.
    If verify is a string, uses that as custom criteria.
    """
    verify = getattr(source, "verify", None)
    gen_prompt = getattr(source, "prompt", "")

    if isinstance(verify, str):
        # Custom criteria — include both the generation prompt and custom check
        return (
            f"This media was generated from the following prompt:\n\n"
            f'"{gen_prompt}"\n\n'
            f"Evaluate it against these specific criteria:\n{verify}\n\n"
            f"Does the generated output satisfy both the original prompt and the criteria above?"
        )
    else:
        # Default: just check prompt adherence
        return (
            f"This media was generated from the following prompt:\n\n"
            f'"{gen_prompt}"\n\n'
            f"To what extent does the generated output actually adhere to this prompt? "
            f"Check for: content accuracy, visual quality, artifacts, and overall coherence. "
            f"Does it match what was requested?"
        )


def _extract_middle_frame(video_path: Path) -> Optional[bytes]:
    """Extract a single frame from the middle of a video using ffmpeg."""
    try:
        # Get duration
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(probe.stdout.strip())
        midpoint = duration / 2

        # Extract frame at midpoint
        result = subprocess.run(
            ["ffmpeg", "-ss", str(midpoint), "-i", str(video_path),
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except Exception as e:
        logger.warning("Failed to extract frame from %s: %s", video_path, e)
    return None


async def verify_media(
    media_path: Path,
    source: Source,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> VerificationEntry:
    """Verify a generated image or video against its source prompt.

    Uses Gemini vision API to analyze the media and check prompt adherence.

    Args:
        media_path: Path to the generated image or video file.
        source: The source that was used to generate this media.
        max_attempts: Max verification API call attempts (for transient failures).

    Returns:
        VerificationEntry with pass/fail, reasoning, and attempt count.
    """
    entry = VerificationEntry()
    verify_prompt = _build_verify_prompt(source)
    media_type = getattr(source, "type", "unknown")

    # Prepare the media for the API
    if media_type == "video":
        # Extract a frame for verification — Gemini can handle video too,
        # but a frame is cheaper and faster for a pass/fail check
        frame_data = _extract_middle_frame(media_path)
        if frame_data is None:
            entry.reason = "Could not extract frame from video for verification"
            entry.used_anyway = True
            return entry
        image_b64 = base64.b64encode(frame_data).decode("utf-8")
        mime = "image/jpeg"
    elif media_type == "image":
        try:
            image_b64 = base64.b64encode(media_path.read_bytes()).decode("utf-8")
        except Exception as e:
            entry.reason = f"Could not read image: {e}"
            entry.used_anyway = True
            return entry
        suffix = media_path.suffix.lower()
        mime = "image/png" if suffix == ".png" else "image/jpeg"
    else:
        entry.reason = f"Unsupported media type for verification: {media_type}"
        entry.used_anyway = True
        return entry

    # Build the Gemini API request
    api_key = _get_gemini_api_key()
    if not api_key:
        entry.reason = "No Gemini API key available for verification"
        entry.used_anyway = True
        return entry

    request_body = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": verify_prompt + "\n\nRespond with a JSON object: {\"passed\": true/false, \"reason\": \"explanation\"}"},
                {
                    "inline_data": {
                        "mime_type": mime,
                        "data": image_b64,
                    }
                },
            ],
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "passed": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["passed", "reason"],
            },
        },
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_VERIFY_MODEL}:generateContent?key={api_key}"

    for attempt in range(1, max_attempts + 1):
        entry.attempts = attempt
        try:
            result = await _call_gemini(url, request_body)
            if result is not None:
                entry.passed = result.get("passed", False)
                entry.reason = result.get("reason", "")
                if entry.passed:
                    logger.info("Verification passed for %s: %s", media_path.name, entry.reason)
                    return entry
                else:
                    logger.warning(
                        "Verification failed for %s (attempt %d/%d): %s",
                        media_path.name, attempt, max_attempts, entry.reason,
                    )
            else:
                entry.reason = "Empty response from verification model"
                logger.warning("Empty verification response for %s (attempt %d)", media_path.name, attempt)

        except Exception as e:
            entry.reason = f"Verification API error: {e}"
            logger.warning("Verification error for %s (attempt %d): %s", media_path.name, attempt, e)

        if attempt < max_attempts:
            await asyncio.sleep(1)

    # All attempts exhausted — mark as used anyway
    entry.used_anyway = True
    return entry


async def _call_gemini(url: str, body: dict) -> Optional[dict]:
    """Call Gemini API and parse the JSON response."""
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Gemini API returned {resp.status}: {text[:200]}")
            data = await resp.json()

    # Parse structured response
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.warning("Failed to parse Gemini response: %s", e)
        return None


def _get_gemini_api_key() -> Optional[str]:
    """Get the Gemini API key from environment."""
    import os
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def write_verification_results(
    run_dir: Path,
    results: Dict[str, VerificationEntry],
) -> Path:
    """Write verification results to verification.json in the run directory."""
    out = {}
    for node_id, entry in results.items():
        out[node_id] = asdict(entry)

    path = run_dir / "verification.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    logger.info("Wrote verification results to %s", path)
    return path
