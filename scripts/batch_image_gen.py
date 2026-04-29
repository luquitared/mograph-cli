#!/usr/bin/env python3
"""Generalized async batch image generation across image backends.

Reads a JSON manifest of image requests, dispatches each to the appropriate
backend (gpt-image-2 via Replicate, nano-banana-2 via Gemini direct), runs
them in parallel, prints per-request success/fail.

Replaces ad-hoc asyncio.gather scripts. For high-volume nano-banana-pro
batches with quality verification, use generation/batch_img.py directly.

Manifest format:

    {
      "requests": [
        {
          "id": "comp-patel",
          "model": "gpt-image-2",            // or "nano-banana-2"
          "prompt": "...",
          "output_path": "runs/x/comp_patel.png",
          "aspect_ratio": "3:2",              // optional, model defaults
          "output_format": "png",             // optional
          "reference_images": ["..."],        // optional, local paths or URLs
          "quality": "high"                   // gpt-image-2 only
        },
        ...
      ],
      "concurrency": 5                        // optional, default 5
    }

Usage:
    python scripts/batch_image_gen.py manifest.json
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generation.gpt_image2 import generate_image as gpt2_generate_image
from generation.nano_banana2 import generate_image as nb2_generate_image


SUPPORTED_MODELS = {"gpt-image-2", "nano-banana-2"}


async def _call_gpt2(session: aiohttp.ClientSession, req: Dict[str, Any]) -> Path:
    path, _log = await gpt2_generate_image(
        session=session,
        prompt=req["prompt"],
        output_path=Path(req["output_path"]),
        aspect_ratio=req.get("aspect_ratio", "1:1"),
        output_format=req.get("output_format", "webp"),
        reference_images=req.get("reference_images"),
        quality=req.get("quality"),
        background=req.get("background"),
        output_compression=req.get("output_compression"),
        moderation=req.get("moderation"),
        max_retries=req.get("max_retries", 5),
    )
    return path


async def _call_nb2(session: aiohttp.ClientSession, req: Dict[str, Any]) -> Path:
    path, _log = await nb2_generate_image(
        session=session,
        prompt=req["prompt"],
        output_path=Path(req["output_path"]),
        aspect_ratio=req.get("aspect_ratio", "1:1"),
        resolution=req.get("resolution", "512"),
        output_format=req.get("output_format", "png"),
        reference_images=req.get("reference_images"),
        max_retries=req.get("max_retries", 5),
    )
    return path


async def _run_one(
    sem: asyncio.Semaphore,
    session: aiohttp.ClientSession,
    req: Dict[str, Any],
) -> Tuple[str, Path]:
    async with sem:
        if req["model"] == "gpt-image-2":
            path = await _call_gpt2(session, req)
        elif req["model"] == "nano-banana-2":
            path = await _call_nb2(session, req)
        else:
            raise ValueError(f"unsupported model: {req['model']}")
        return req["id"], path


def _validate(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "requests" not in manifest or not isinstance(manifest["requests"], list):
        raise ValueError("manifest must have a 'requests' array")
    requests = manifest["requests"]
    seen_ids: set = set()
    for i, req in enumerate(requests):
        for key in ("id", "model", "prompt", "output_path"):
            if key not in req:
                raise ValueError(f"request[{i}] missing required field '{key}'")
        if req["model"] not in SUPPORTED_MODELS:
            raise ValueError(
                f"request[{i}] '{req['id']}': unsupported model '{req['model']}' "
                f"(supported: {sorted(SUPPORTED_MODELS)})"
            )
        if req["id"] in seen_ids:
            raise ValueError(f"duplicate request id: {req['id']}")
        seen_ids.add(req["id"])
    return requests


async def run_manifest(manifest_path: Path) -> int:
    manifest = json.loads(manifest_path.read_text())
    requests = _validate(manifest)
    concurrency = int(manifest.get("concurrency", 5))

    needs_replicate = any(r["model"] == "gpt-image-2" for r in requests)
    needs_gemini = any(r["model"] == "nano-banana-2" for r in requests)

    if needs_replicate and not os.environ.get("REPLICATE_API_TOKEN"):
        raise EnvironmentError("REPLICATE_API_TOKEN not set (needed for gpt-image-2)")
    if needs_gemini and not os.environ.get("GOOGLE_API_KEY"):
        raise EnvironmentError("GOOGLE_API_KEY not set (needed for nano-banana-2)")

    sem = asyncio.Semaphore(concurrency)

    rep_session: aiohttp.ClientSession | None = None
    gem_session: aiohttp.ClientSession | None = None
    try:
        if needs_replicate:
            rep_session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {os.environ['REPLICATE_API_TOKEN']}"}
            )
        if needs_gemini:
            gem_session = aiohttp.ClientSession()

        coros = []
        for req in requests:
            session = rep_session if req["model"] == "gpt-image-2" else gem_session
            coros.append(_run_one(sem, session, req))

        results = await asyncio.gather(*coros, return_exceptions=True)
    finally:
        if rep_session is not None:
            await rep_session.close()
        if gem_session is not None:
            await gem_session.close()

    fails = 0
    for req, res in zip(requests, results):
        if isinstance(res, Exception):
            fails += 1
            print(f"[FAIL] {req['id']} ({req['model']}): {res}")
        else:
            _id, path = res
            print(f"[OK]   {req['id']} ({req['model']}): {path}")

    print(f"\n{len(requests) - fails}/{len(requests)} succeeded")
    return 0 if fails == 0 else 1


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: batch_image_gen.py <manifest.json>", file=sys.stderr)
        return 2
    manifest_path = Path(sys.argv[1])
    if not manifest_path.is_file():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    return asyncio.run(run_manifest(manifest_path))


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
