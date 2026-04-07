#!/usr/bin/env python3
"""Watch a video and get a detailed summary.

Usage:
    python watch.py video.mp4
    python watch.py video.mp4 --prompt "What products are shown?"
    python watch.py video.mp4 --json
"""

import argparse
import json
import os
import sys
from pathlib import Path

from google import genai
from google.genai import types


def get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: set GEMINI_API_KEY or GOOGLE_API_KEY", file=sys.stderr)
        sys.exit(1)
    return genai.Client(api_key=api_key)


def watch(video_path: Path, prompt: str | None = None, model: str = "gemini-3.1-pro-preview") -> dict:
    """Analyze a video and return a structured summary."""
    client = get_client()

    if not video_path.exists():
        print(f"Error: {video_path} not found", file=sys.stderr)
        sys.exit(1)

    # Upload the video file
    print(f"Uploading {video_path.name}...", file=sys.stderr)
    uploaded = client.files.upload(file=video_path)

    # Wait for processing
    import time
    while uploaded.state.name == "PROCESSING":
        time.sleep(2)
        uploaded = client.files.get(name=uploaded.name)

    if uploaded.state.name == "FAILED":
        print(f"Error: video processing failed", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing with {model}...", file=sys.stderr)

    default_prompt = """Analyze this video in detail. Provide:

1. **Overview** — What is this video about? What's the main subject/purpose?
2. **Visual Style** — Describe the visual style, color palette, camera work, and production quality.
3. **Scene Breakdown** — List each distinct scene/segment with timestamps and what happens.
4. **Audio** — Describe any narration, music, sound effects, or dialogue.
5. **Text/Graphics** — Note any on-screen text, titles, lower thirds, or graphic overlays.
6. **Key Takeaways** — What are the main points or messages?
7. **Technical Notes** — Resolution quality, aspect ratio, any notable production techniques.

Be specific and detailed. Include timestamps where possible."""

    user_prompt = prompt or default_prompt

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
                    types.Part.from_text(text=user_prompt),
                ],
            )
        ],
    )

    # Clean up uploaded file
    try:
        client.files.delete(name=uploaded.name)
    except Exception:
        pass

    return {
        "video": str(video_path),
        "model": model,
        "prompt": user_prompt,
        "summary": response.text,
    }


def main():
    parser = argparse.ArgumentParser(description="Watch a video and get a detailed summary")
    parser.add_argument("video", type=Path, help="Path to the video file")
    parser.add_argument("--prompt", "-p", type=str, default=None, help="Custom analysis prompt")
    parser.add_argument("--model", "-m", type=str, default="gemini-3.1-pro-preview", help="Gemini model to use")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = watch(args.video, prompt=args.prompt, model=args.model)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["summary"])


if __name__ == "__main__":
    main()
