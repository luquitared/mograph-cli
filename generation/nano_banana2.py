"""Nano Banana 2 — direct Gemini 3.1 Flash Image Preview API.

Super-fast image generation using the Gemini generativeai endpoint directly,
bypassing Replicate entirely. Uses burst mode config for maximum throughput:
512px, minimal thinking, IMAGE-only response.
"""

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

MODEL_ID = "gemini-3.1-flash-image-preview"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent"

# Aspect ratios supported by Gemini image generation
VALID_ASPECT_RATIOS = {
    "1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3",
    "4:5", "5:4", "21:9", "1:4", "4:1", "1:8", "8:1",
}

# Resolution mapping: timeline resolution names → Gemini imageSize values
RESOLUTION_MAP = {
    "512": "512",
    "1K": "1K",
    "2K": "2K",
    "4K": "4K",
}

# Mock mode
MOCK_GENERATE = False
MOCK_IMAGE_FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "mock_image.png"


async def generate_image(
    session: aiohttp.ClientSession,
    prompt: str,
    output_path: Path,
    aspect_ratio: str = "1:1",
    resolution: str = "512",
    output_format: str = "png",
    reference_images: Optional[list] = None,
    max_retries: int = 5,
) -> Tuple[Path, list]:
    """Generate a single image via the Gemini API (burst mode).

    Args:
        session: aiohttp session (no auth headers needed, key is in query param).
        prompt: Text prompt for image generation.
        output_path: Where to write the output image.
        aspect_ratio: Aspect ratio (e.g. "1:1", "16:9").
        resolution: Image size — "512" (burst default), "1K", "2K", "4K".
        output_format: "png" or "jpg".
        reference_images: Optional list of local file paths for image editing.
        max_retries: Max retry attempts on failure.

    Returns:
        Tuple of (output_path, attempt_log).
    """
    if MOCK_GENERATE:
        import shutil
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MOCK_IMAGE_FIXTURE, output_path)
        return output_path, [{"attempt": 1, "success": True, "mock": True}]

    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GOOGLE_API_KEY not set (required for nano-banana-2)")

    image_size = RESOLUTION_MAP.get(resolution, "512")

    # Build content parts
    parts: list[Dict[str, Any]] = []

    # Add reference images if provided (for image editing / style reference)
    if reference_images:
        for img_path in reference_images:
            p = Path(img_path).expanduser().resolve()
            if p.exists():
                img_data = base64.b64encode(p.read_bytes()).decode("utf-8")
                mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
                parts.append({"inlineData": {"mimeType": mime, "data": img_data}})

    parts.append({"text": prompt})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
                "imageSize": image_size,
            },
            "thinkingConfig": {
                "thinking_level": "minimal",
            },
        },
    }

    url = f"{ENDPOINT}?key={api_key}"
    attempt_log = []
    last_error = None

    for attempt in range(1, max_retries + 1):
        entry = {"attempt": attempt, "success": False, "error": None}

        try:
            logger.info("[nano-banana-2] Generating image (attempt %d/%d)…", attempt, max_retries)
            async with session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Gemini API {resp.status}: {body[:500]}")

                data = await resp.json()

            # Extract base64 image from response
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError(f"No candidates in Gemini response: {json.dumps(data)[:300]}")

            parts_out = candidates[0].get("content", {}).get("parts", [])
            image_part = next((p for p in parts_out if "inlineData" in p), None)
            if not image_part:
                raise RuntimeError(f"No image in Gemini response parts: {[list(p.keys()) for p in parts_out]}")

            b64_data = image_part["inlineData"]["data"]
            mime_type = image_part["inlineData"].get("mimeType", "image/png")

            # Determine output extension from mime if needed
            img_bytes = base64.b64decode(b64_data)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(img_bytes)

            entry["success"] = True
            attempt_log.append(entry)
            logger.info("[nano-banana-2] Done: %s (%d bytes)", output_path.name, len(img_bytes))
            return output_path, attempt_log

        except Exception as e:
            last_error = e
            entry["error"] = str(e)
            attempt_log.append(entry)
            logger.warning("[nano-banana-2] Attempt %d failed: %s", attempt, e)

            if attempt < max_retries:
                wait = min(2 ** attempt, 30)
                await asyncio.sleep(wait)

    raise RuntimeError(
        f"Nano Banana 2 generation failed after {max_retries} attempts. Last error: {last_error}"
    )
