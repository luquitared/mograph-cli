#!/usr/bin/env python3
"""
Batch image generation using google/nano-banana-pro via Replicate.

Async implementation for high-throughput image generation.
Supports:
- Text prompts with optional reference images
- Configurable aspect ratios, resolutions, output formats
- Concurrent predictions with semaphore control

Input JSON formats:
- New (simpler):
  {
    "requests": [
      {
        "prompt": "...",
        "image_paths": ["path/to/reference.png"],
        "filename": "output.png",
        "output_dir": "images",
        "config": {...}
      }
    ]
  }
- Legacy (still supported):
  {
    "default_messages": [{"role": "user", "parts": [{"text": "..."}, {"image_path": "..."}]}],
    "requests": [{"append_messages": [...], ...}]
  }

Env:
  export REPLICATE_API_TOKEN=...
"""
import argparse
import asyncio
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp
from openai import AsyncOpenAI

from shared.common import ensure_dir, guess_mime_image, sanitize_filename
from shared.replicate_client import (
    upload_file_to_replicate,
    start_prediction,
    poll_prediction,
    download_to,
)

MODEL_OWNER = "google"
MODEL_NAME = "nano-banana-pro"

# Mock mode - set by pipeline when --mock flag is passed
MOCK_REPLICATE = False
MOCK_IMAGE_FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "mock_image.png"


# -------------------- Image verification --------------------

async def verify_image_quality(
    client: AsyncOpenAI,
    image_path: Path,
    expected_prompt: str,
    max_attempts: int = 5,
) -> Dict[str, Any]:
    """
    Verify image quality using OpenAI vision API.

    Returns verification result with structure:
    {
        "image_path": str,
        "passed": bool,
        "attempts": int,
        "issues": List[str],
        "timestamp": str,
        "error": Optional[str],
        "attempt_log": List[Dict[str, Any]]
    }
    """
    result = {
        "image_path": str(image_path),
        "passed": False,
        "attempts": 0,
        "issues": [],
        "timestamp": datetime.utcnow().isoformat(),
        "error": None,
        "attempt_log": [],
    }

    # Encode image to base64
    try:
        image_data = base64.b64encode(image_path.read_bytes()).decode('utf-8')
        mime_type = guess_mime_image(image_path)
    except Exception as e:
        result["error"] = f"Failed to read image: {e}"
        return result

    verification_prompt = f"""Analyze this generated image and check for quality issues.

Expected content: {expected_prompt}

Check for:
1. Text quality: text is allowed. Flag only if misspelled, garbled, or unreadable.
2. Text is legible, contrast is good, text is not ontop of other text.
3. Visual artifacts (distortion, corruption, weird glitches)
4. Aspect ratio problems (stretched, squashed, wrong proportions)
5. Missing or incorrect content based on the prompt
6. Overall quality and coherence

Use the verify_image_quality function to report your findings."""

    # Define verification tool schema
    verification_tool = {
        "type": "function",
        "function": {
            "name": "verify_image_quality",
            "description": "Report image quality verification results",
            "parameters": {
                "type": "object",
                "properties": {
                    "passed": {
                        "type": "boolean",
                        "description": "True if image is good quality with no major issues, false otherwise"
                    },
                    "issues": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Array of specific problems found. Empty array if passed is true."
                    }
                },
                "required": ["passed", "issues"],
                "additionalProperties": False
            }
        }
    }

    for attempt in range(1, max_attempts + 1):
        result["attempts"] = attempt
        attempt_log_entry = {
            "attempt_number": attempt,
            "timestamp": datetime.utcnow().isoformat(),
            "success": False,
            "error": None,
            "response": None,
        }

        try:
            response = await client.chat.completions.create(
                model="gpt-5-mini-2025-08-07",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": verification_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                tools=[verification_tool],
                tool_choice={"type": "function", "function": {"name": "verify_image_quality"}},
            )

            # Parse tool call response
            message = response.choices[0].message
            if not message.tool_calls:
                raise ValueError("No tool call in response")

            tool_call = message.tool_calls[0]
            verification_data = json.loads(tool_call.function.arguments)

            # Log successful attempt
            attempt_log_entry["success"] = True
            attempt_log_entry["response"] = verification_data
            result["attempt_log"].append(attempt_log_entry)

            result["passed"] = verification_data.get("passed", False)
            result["issues"] = verification_data.get("issues", [])

            # If passed, we're done
            if result["passed"]:
                break

        except Exception as e:
            # Log failed attempt
            attempt_log_entry["error"] = str(e)
            result["attempt_log"].append(attempt_log_entry)
            result["error"] = f"Attempt {attempt} failed: {e}"

            if attempt < max_attempts:
                await asyncio.sleep(1)  # Brief delay before retry
            continue

    return result


async def verify_batch_images(
    image_paths: List[Path],
    prompts: List[str],
    max_attempts: int = 5,
) -> Dict[str, Any]:
    """
    Verify a batch of generated images.

    Returns:
    {
        "timestamp": str,
        "total_images": int,
        "passed": int,
        "failed": int,
        "results": List[verification_result]
    }
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("⚠️  OPENAI_API_KEY not set, skipping verification")
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_images": len(image_paths),
            "passed": 0,
            "failed": 0,
            "results": [],
            "skipped": True,
        }

    client = AsyncOpenAI(api_key=api_key)

    print(f"\n🔍 Verifying {len(image_paths)} images with OpenAI vision (max {max_attempts} attempts per image)...")

    # Run verifications concurrently
    tasks = [
        verify_image_quality(client, img_path, prompt, max_attempts)
        for img_path, prompt in zip(image_paths, prompts)
    ]
    results = await asyncio.gather(*tasks)

    # Summarize results
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_images": len(image_paths),
        "passed": passed,
        "failed": failed,
        "results": results,
    }

    # Print summary
    print(f"✅ Passed: {passed}/{len(image_paths)}")
    if failed > 0:
        print(f"❌ Failed: {failed}/{len(image_paths)}")
        for r in results:
            if not r["passed"]:
                print(f"   {Path(r['image_path']).name}: {', '.join(r['issues']) if r['issues'] else r.get('error', 'Unknown error')}")

    return summary


# -------------------- Message parsing --------------------

def extract_prompt_and_images(messages: List[Dict[str, Any]], request: Optional[Dict[str, Any]] = None) -> tuple[str, List[Path]]:
    """
    Extract text prompt and image paths from messages or direct request fields.
    Supports both legacy message-based format and simplified prompt/image_paths.
    """
    prompt_parts: List[str] = []
    image_paths: List[Path] = []

    for msg in messages:
        parts = msg.get("parts", [])
        for part in parts:
            if "text" in part:
                prompt_parts.append(str(part["text"]))
            elif "image_path" in part:
                p = Path(part["image_path"]).expanduser().resolve()
                if p.exists():
                    image_paths.append(p)

    # New format: prompt + image_paths/reference_images directly on request
    if request:
        direct_prompt = request.get("prompt")
        if direct_prompt:
            prompt_parts.append(str(direct_prompt))
        for key in ("image_paths", "reference_images"):
            for img in request.get(key, []) or []:
                p = Path(img).expanduser().resolve()
                if p.exists():
                    image_paths.append(p)

    prompt = " ".join(prompt_parts).strip()
    return prompt, image_paths


# -------------------- Core job processing --------------------

async def generate_single_image(
    session: aiohttp.ClientSession,
    default_messages: List[Dict[str, Any]],
    request: Dict[str, Any],
    idx: int,
    poll_sec: float,
    output_dir: Path,
    max_replicate_retries: int = 5,
) -> Tuple[Path, List[Dict[str, Any]]]:
    """
    Generate a single image with Replicate API retry logic.

    Returns:
        Tuple of (image_path, replicate_attempt_log)
    """
    # Merge default + append messages
    all_messages = list(default_messages) + request.get("append_messages", [])

    # Extract prompt and images
    prompt, image_paths = extract_prompt_and_images(all_messages, request)
    if not prompt:
        raise ValueError(f"Request {idx}: No prompt found in messages")

    # Upload reference images if provided
    image_urls = []
    for img_path in image_paths:
        url = await upload_file_to_replicate(session, img_path)
        image_urls.append(url)

    # Get config (with defaults)
    config = request.get("config", {})
    aspect_ratio = config.get("aspect_ratio", "9:16")  # Default to 9:16 for vertical videos
    resolution = config.get("resolution", "2K")
    output_format = config.get("output_format", "png")
    safety_filter_level = config.get("safety_filter_level", "block_only_high")

    # Build Replicate inputs
    inputs = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "output_format": output_format,
        "safety_filter_level": safety_filter_level,
        "image_input": image_urls,  # Can be empty list
    }

    filename = request.get("filename", f"output_{idx}.{output_format}")
    ensure_dir(output_dir)
    dest = output_dir / filename

    replicate_log = []
    last_error = None

    # Retry loop for Replicate API
    for attempt in range(1, max_replicate_retries + 1):
        attempt_entry = {
            "attempt_number": attempt,
            "timestamp": datetime.utcnow().isoformat(),
            "success": False,
            "error": None,
        }

        try:
            print(f"🚀 [{idx}] Creating prediction ({MODEL_OWNER}/{MODEL_NAME})… (Replicate attempt {attempt}/{max_replicate_retries})")
            pred = await start_prediction(session, MODEL_OWNER, MODEL_NAME, inputs, mock_fixture=MOCK_IMAGE_FIXTURE if MOCK_REPLICATE else None)
            pred = await poll_prediction(session, pred, poll_sec=poll_sec)

            # Get output URL (single image URL string)
            output_url = pred.get("output")
            if not output_url or not isinstance(output_url, str):
                raise RuntimeError(f"No output URL in prediction: {pred}")

            print(f"⬇️  [{idx}] Downloading result → {dest.name}")
            await download_to(session, output_url, dest)
            print(f"✅ [{idx}] Done: {dest}")

            # Success!
            attempt_entry["success"] = True
            replicate_log.append(attempt_entry)
            return dest, replicate_log

        except Exception as e:
            last_error = e
            attempt_entry["error"] = str(e)
            replicate_log.append(attempt_entry)

            print(f"❌ [{idx}] Replicate error (attempt {attempt}/{max_replicate_retries}): {e}")

            if attempt < max_replicate_retries:
                wait_time = min(2 ** attempt, 30)  # Exponential backoff, max 30s
                print(f"⏳ [{idx}] Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
            else:
                print(f"⚠️  [{idx}] All {max_replicate_retries} Replicate attempts failed")

    # All attempts failed
    raise RuntimeError(f"Replicate generation failed after {max_replicate_retries} attempts. Last error: {last_error}")


async def process_request(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    default_messages: List[Dict[str, Any]],
    request: Dict[str, Any],
    idx: int,
    poll_sec: float,
    verify_quality: bool = False,
    max_verification_attempts: int = 5,
    max_replicate_retries: int = 5,
    openai_client: Optional[AsyncOpenAI] = None,
    attempt_log_dir: Optional[Path] = None,
) -> Tuple[Path, Dict[str, Any]]:
    """
    Process a single image generation request with optional quality verification and retry.

    Returns:
        Tuple of (image_path, generation_log)
    """
    async with sem:
        output_dir = Path(request.get("output_dir", "."))
        failed_dir = output_dir.parent / "failed_images"

        # Extract prompt for verification
        all_messages = list(default_messages) + request.get("append_messages", [])
        prompt, _ = extract_prompt_and_images(all_messages, request)

        filename = request.get("filename", f"output_{idx}.png")

        generation_log = {
            "filename": filename,
            "prompt": prompt,
            "verification_attempts": [],
            "final_status": "failed",
            "final_path": None,
        }

        dest = None
        for verification_attempt in range(1, max_verification_attempts + 1):
            attempt_log = {
                "verification_attempt": verification_attempt,
                "replicate_log": [],
                "verification_result": None,
                "outcome": None,
            }

            try:
                # Generate image (with Replicate retry logic)
                dest, replicate_log = await generate_single_image(
                    session,
                    default_messages,
                    request,
                    idx,
                    poll_sec,
                    output_dir,
                    max_replicate_retries=max_replicate_retries,
                )
                attempt_log["replicate_log"] = replicate_log

            except Exception as e:
                # Replicate generation failed completely
                attempt_log["outcome"] = "replicate_failed"
                attempt_log["error"] = str(e)
                generation_log["verification_attempts"].append(attempt_log)
                print(f"❌ [{idx}] Replicate generation failed on verification attempt {verification_attempt}: {e}")

                if attempt_log_dir:
                    ensure_dir(attempt_log_dir)
                    attempt_path = attempt_log_dir / f"{idx:03d}_{sanitize_filename(filename)}_attempt{verification_attempt}.json"
                    attempt_path.write_text(json.dumps({"index": idx, "filename": filename, "attempt": attempt_log}, indent=2))

                if verification_attempt < max_verification_attempts:
                    print(f"🔄 [{idx}] Retrying verification attempt {verification_attempt + 1}/{max_verification_attempts}...")
                    continue
                else:
                    raise RuntimeError(f"Failed to generate image after {max_verification_attempts} verification attempts")

            # If verification disabled, we're done
            if not verify_quality or not openai_client:
                attempt_log["outcome"] = "no_verification"
                generation_log["verification_attempts"].append(attempt_log)
                generation_log["final_status"] = "success"
                generation_log["final_path"] = str(dest)

                if attempt_log_dir:
                    ensure_dir(attempt_log_dir)
                    attempt_path = attempt_log_dir / f"{idx:03d}_{sanitize_filename(filename)}_attempt{verification_attempt}.json"
                    attempt_path.write_text(json.dumps({"index": idx, "filename": filename, "attempt": attempt_log}, indent=2))
                return dest, generation_log

            # Verify the generated image
            print(f"🔍 [{idx}] Verifying quality (verification attempt {verification_attempt}/{max_verification_attempts})...")
            verification = await verify_image_quality(
                openai_client, dest, prompt, max_attempts=1  # Single check per generation
            )
            attempt_log["verification_result"] = verification

            if verification["passed"]:
                print(f"✅ [{idx}] Verification passed")
                attempt_log["outcome"] = "success"
                generation_log["verification_attempts"].append(attempt_log)
                generation_log["final_status"] = "success"
                generation_log["final_path"] = str(dest)

                if attempt_log_dir:
                    ensure_dir(attempt_log_dir)
                    attempt_path = attempt_log_dir / f"{idx:03d}_{sanitize_filename(filename)}_attempt{verification_attempt}.json"
                    attempt_path.write_text(json.dumps({"index": idx, "filename": filename, "attempt": attempt_log}, indent=2))
                return dest, generation_log

            # Failed verification - move to failed_images
            issues = verification.get('issues', [])
            issues_str = ', '.join(str(i) for i in issues) if issues else 'Unknown issues'
            print(f"❌ [{idx}] Verification failed: {issues_str}")
            attempt_log["outcome"] = "verification_failed"

            if verification_attempt < max_verification_attempts:
                # Move failed image
                ensure_dir(failed_dir)
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                failed_filename = f"{dest.stem}_verif_attempt{verification_attempt}_{timestamp}{dest.suffix}"
                failed_path = failed_dir / failed_filename
                dest.rename(failed_path)
                attempt_log["failed_image_path"] = str(failed_path)
                generation_log["verification_attempts"].append(attempt_log)

                print(f"📁 [{idx}] Moved failed image to {failed_path}")
                print(f"🔄 [{idx}] Regenerating (verification attempt {verification_attempt + 1}/{max_verification_attempts})...")
            else:
                # Final attempt failed - still move it
                ensure_dir(failed_dir)
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                failed_filename = f"{dest.stem}_verif_attempt{verification_attempt}_{timestamp}_FINAL_FAILED{dest.suffix}"
                failed_path = failed_dir / failed_filename
                dest.rename(failed_path)
                attempt_log["failed_image_path"] = str(failed_path)
                generation_log["verification_attempts"].append(attempt_log)

                print(f"⚠️  [{idx}] All {max_verification_attempts} verification attempts failed. Last image moved to {failed_path}")
                raise RuntimeError(f"Image failed verification after {max_verification_attempts} attempts: {verification['issues']}")

            if attempt_log_dir:
                ensure_dir(attempt_log_dir)
                attempt_path = attempt_log_dir / f"{idx:03d}_{sanitize_filename(filename)}_attempt{verification_attempt}.json"
                attempt_path.write_text(json.dumps({"index": idx, "filename": filename, "attempt": attempt_log}, indent=2))

        return dest, generation_log


# -------------------- Batch runner --------------------

async def run_batch_async(
    json_path: Path,
    concurrency: int = 4,
    poll_sec: float = 2.0,
    verify_misspellings: bool = True,
    max_verification_attempts: int = 5,
    max_replicate_retries: int = 5,
) -> List[Path]:
    """Run batch image generation with optional verification and auto-regeneration."""
    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        raise EnvironmentError("REPLICATE_API_TOKEN not set.")

    # Load config
    with open(json_path, "r") as f:
        cfg = json.load(f)

    default_messages = cfg.get("default_messages") or []
    requests = cfg.get("requests") or []

    if not isinstance(default_messages, list) or not isinstance(requests, list):
        raise SystemExit("JSON must include 'requests' (list) and optional 'default_messages' (list).")

    if not requests:
        raise SystemExit("No requests found in JSON.")

    # Setup OpenAI client if verification enabled
    openai_client = None
    if verify_misspellings:
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            openai_client = AsyncOpenAI(api_key=api_key)
            print(f"🔍 Verification enabled with auto-regeneration")
            print(f"   Max verification attempts per image: {max_verification_attempts}")
            print(f"   Max Replicate retries per generation: {max_replicate_retries}")
        else:
            print("⚠️  OPENAI_API_KEY not set, skipping verification")
            verify_misspellings = False

    headers = {"Authorization": f"Bearer {token}"}
    sem = asyncio.Semaphore(concurrency)
    attempt_log_dir = json_path.parent / f"{json_path.stem}_attempt_logs"

    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=None)) as session:
        tasks = [
            process_request(
                session,
                sem,
                default_messages,
                req,
                idx=i + 1,
                poll_sec=poll_sec,
                verify_quality=verify_misspellings,
                max_verification_attempts=max_verification_attempts,
                max_replicate_retries=max_replicate_retries,
                openai_client=openai_client,
                attempt_log_dir=attempt_log_dir,
            )
            for i, req in enumerate(requests)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect results and report errors
    paths: List[Path] = []
    generation_logs = []
    had_errors = False

    for i, res in enumerate(results, start=1):
        if isinstance(res, Exception):
            had_errors = True
            print(f"❌ [{i}] ERROR: {res}", file=sys.stderr)
            generation_logs.append({
                "index": i,
                "filename": requests[i-1].get("filename", f"output_{i}.png"),
                "final_status": "failed",
                "error": str(res),
            })
        else:
            path, log = res
            paths.append(path)
            log["index"] = i
            generation_logs.append(log)

    if had_errors:
        print("⚠️  Some requests failed. Successful outputs are still returned.")

    # Save comprehensive generation log
    if generation_logs:
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_images": len(requests),
            "successful": len(paths),
            "failed": len(requests) - len(paths),
            "settings": {
                "verification_enabled": verify_misspellings,
                "max_verification_attempts": max_verification_attempts,
                "max_replicate_retries": max_replicate_retries,
            },
            "generation_logs": generation_logs,
        }

        log_path = json_path.parent / f"{json_path.stem}_generation_log.json"
        with open(log_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"📝 Generation log saved to {log_path}")

    return paths


async def run_batch_streaming(
    json_path: Path,
    concurrency: int = 4,
    poll_sec: float = 2.0,
    verify_misspellings: bool = True,
    max_verification_attempts: int = 5,
    max_replicate_retries: int = 5,
    on_image_complete: Optional[Callable[[int, Path, Dict[str, Any]], None]] = None,
) -> List[Path]:
    """
    Streaming version of batch image generation that calls a callback as each image completes.

    This enables Stage 1 & 2 overlap by allowing video generation to start
    before all images are done.

    Args:
        json_path: Path to batch config JSON
        concurrency: Max concurrent image generations
        poll_sec: Polling interval for Replicate
        verify_misspellings: Whether to verify image quality
        max_verification_attempts: Max verification retries
        max_replicate_retries: Max Replicate API retries
        on_image_complete: Async callback(index, path, request_data) called when each image completes

    Returns:
        List of generated image paths
    """
    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        raise EnvironmentError("REPLICATE_API_TOKEN is not set")

    with open(json_path, "r") as f:
        cfg = json.load(f)

    default_messages = cfg.get("default_messages") or []
    requests = cfg.get("requests") or []

    if not isinstance(default_messages, list) or not isinstance(requests, list):
        raise SystemExit("JSON must include 'requests' (list) and optional 'default_messages' (list).")

    if not requests:
        raise SystemExit("No requests found in JSON.")

    # Setup OpenAI client if verification enabled
    openai_client = None
    if verify_misspellings:
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            openai_client = AsyncOpenAI(api_key=api_key)
            print(f"🔍 Verification enabled with auto-regeneration")
        else:
            print("⚠️  OPENAI_API_KEY not set, skipping verification")
            verify_misspellings = False

    headers = {"Authorization": f"Bearer {token}"}
    sem = asyncio.Semaphore(concurrency)
    attempt_log_dir = json_path.parent / f"{json_path.stem}_attempt_logs"

    paths: List[Path] = []
    generation_logs = []
    had_errors = False

    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=None)) as session:
        # Create tasks with their indices stored as task names
        task_to_info: Dict[asyncio.Task, Tuple[int, Dict[str, Any]]] = {}
        for i, req in enumerate(requests):
            task = asyncio.create_task(
                process_request(
                    session,
                    sem,
                    default_messages,
                    req,
                    idx=i + 1,
                    poll_sec=poll_sec,
                    verify_quality=verify_misspellings,
                    max_verification_attempts=max_verification_attempts,
                    max_replicate_retries=max_replicate_retries,
                    openai_client=openai_client,
                    attempt_log_dir=attempt_log_dir,
                )
            )
            task_to_info[task] = (i, req)

        # Process results as they complete (streaming)
        for coro in asyncio.as_completed(list(task_to_info.keys())):
            try:
                res = await coro
                # Find which task this was
                completed_task = None
                for t, (idx, req) in task_to_info.items():
                    if t.done():
                        try:
                            t_res = t.result()
                            if t_res == res:
                                completed_task = t
                                break
                        except Exception:
                            pass

                if completed_task is None:
                    # Fallback: find any done task we haven't processed
                    for t, (idx, req) in list(task_to_info.items()):
                        if t.done():
                            completed_task = t
                            break

                if completed_task is not None:
                    idx, req = task_to_info.pop(completed_task)

                    if isinstance(res, Exception):
                        had_errors = True
                        print(f"❌ [{idx + 1}] ERROR: {res}", file=sys.stderr)
                        generation_logs.append({
                            "index": idx + 1,
                            "filename": req.get("filename", f"output_{idx + 1}.png"),
                            "final_status": "failed",
                            "error": str(res),
                        })
                    else:
                        path, log = res
                        paths.append(path)
                        log["index"] = idx + 1
                        generation_logs.append(log)

                        # Call the streaming callback
                        if on_image_complete:
                            try:
                                callback_result = on_image_complete(idx, path, req)
                                if asyncio.iscoroutine(callback_result):
                                    await callback_result
                            except Exception as cb_err:
                                print(f"⚠️  Callback error for image {idx + 1}: {cb_err}")

            except Exception as e:
                had_errors = True
                print(f"❌ ERROR: {e}", file=sys.stderr)
                generation_logs.append({
                    "index": -1,
                    "filename": "unknown",
                    "final_status": "failed",
                    "error": str(e),
                })

    if had_errors:
        print("⚠️  Some requests failed. Successful outputs are still returned.")

    # Save generation log
    if generation_logs:
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_images": len(requests),
            "successful": len(paths),
            "failed": len(requests) - len(paths),
            "settings": {
                "verification_enabled": verify_misspellings,
                "max_verification_attempts": max_verification_attempts,
                "max_replicate_retries": max_replicate_retries,
            },
            "generation_logs": generation_logs,
        }

        log_path = json_path.parent / f"{json_path.stem}_generation_log.json"
        with open(log_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"📝 Generation log saved to {log_path}")

    return paths


def run_batch(
    batch_path,
    model: str = "google/nano-banana-pro",
    concurrency: int = 4,
    max_images: Optional[int] = None,
    max_attempts: int = 5,
    verify_misspellings: bool = True,
    target_aspect_ratio: Optional[float] = None,
    poll_sec: float = 2.0,
    max_replicate_retries: int = 5,
) -> List[Path]:
    """
    Synchronous wrapper for batch image generation.
    Legacy compatibility layer for pipeline.

    Note: model, max_images, and target_aspect_ratio are currently ignored
    in the new Replicate-based implementation.
    max_attempts is used for verification retries.
    max_replicate_retries is used for Replicate API retries.
    """
    return asyncio.run(run_batch_async(
        json_path=Path(batch_path),
        concurrency=concurrency,
        poll_sec=poll_sec,
        verify_misspellings=verify_misspellings,
        max_verification_attempts=max_attempts,
        max_replicate_retries=max_replicate_retries,
    ))


def main():
    parser = argparse.ArgumentParser(description="Batch Nano Banana Pro image generation via Replicate.")
    parser.add_argument("json_path", help="Path to input JSON")
    parser.add_argument("--concurrency", type=int, default=4, help="Max concurrent requests (default: 4)")
    parser.add_argument("--poll-sec", type=float, default=2.0, help="Polling interval in seconds (default: 2.0)")
    parser.add_argument("--verify", action="store_true", default=True, help="Verify image quality with OpenAI vision (default: True)")
    parser.add_argument("--no-verify", dest="verify", action="store_false", help="Skip image verification")
    parser.add_argument("--max-verification-attempts", type=int, default=5, help="Max verification retry attempts per image (default: 5)")
    parser.add_argument("--max-replicate-retries", type=int, default=5, help="Max Replicate API retry attempts per generation (default: 5)")
    args = parser.parse_args()

    paths = asyncio.run(run_batch_async(
        json_path=Path(args.json_path),
        concurrency=args.concurrency,
        poll_sec=args.poll_sec,
        verify_misspellings=args.verify,
        max_verification_attempts=args.max_verification_attempts,
        max_replicate_retries=args.max_replicate_retries,
    ))

    print(f"\n✅ Generated {len(paths)} images")
    for p in paths:
        print(f"  {p}")


if __name__ == "__main__":
    main()
