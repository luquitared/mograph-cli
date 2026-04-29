#!/usr/bin/env python3
"""Holistic Gemini critique of an assembled video. Returns structured JSON."""

import json
import os
import sys
import time

from google import genai
from google.genai import types


MODEL_ID = "gemini-3.1-pro-preview"

SCHEMA = {
    "type": "object",
    "properties": {
        "duration_sec": {"type": "number"},
        "structure": {
            "type": "string",
            "description": "Beat-by-beat outline of what happens",
        },
        "what_works": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific things that land well — concrete, not generic",
        },
        "what_doesnt_work": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific weaknesses — pacing, voice continuity, joke landings, visual inconsistencies, audio jumps, motion issues, anything that breaks immersion",
        },
        "character_consistency": {
            "type": "string",
            "description": "Do Maya, Trip, and FAQ-9000 look and sound consistent across their multiple appearances? Note specific drift",
        },
        "audio_quality": {
            "type": "string",
            "description": "Voice clarity, level matching across cuts, audible artifacts, voice consistency for each character",
        },
        "comedic_landing": {
            "type": "string",
            "description": "Are the jokes actually funny? Which lines land, which fall flat",
        },
        "biggest_fixes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Top 3-5 highest-leverage changes that would most improve the video. Be concrete and prescriptive",
        },
        "overall_score": {
            "type": "integer",
            "description": "1-10 overall quality",
        },
    },
    "required": [
        "duration_sec", "structure", "what_works", "what_doesnt_work",
        "character_consistency", "audio_quality", "comedic_landing",
        "biggest_fixes", "overall_score",
    ],
}


PROMPT = """Watch this assembled news-show video end-to-end and critique it like a tough but constructive editor.

Brief context: this is a satirical news segment doing a top-5 breakdown of political prediction markets. Cast:
- Maya — sharp female anchor, sakuga anime style
- Trip — blonde himbo co-host, sakuga anime style
- FAQ-9000 — deadpan tin robot
The video interleaves on-set scenes (all three at the news desk) with b-roll cutaways (no characters, just scene visuals + Maya VO).

Be specific and concrete. Don't pad. Call out what fails by timestamp where useful. Surface character drift,
audio level jumps, jokes that don't land, pacing problems, anything that pulls a viewer out. End with the
top fixes ranked by leverage."""


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: critique_full_video.py <video_file>", file=sys.stderr)
        return 2

    video_path = sys.argv[1]
    if not os.path.exists(video_path):
        print(f"file not found: {video_path}", file=sys.stderr)
        return 2

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY not set", file=sys.stderr)
        return 2

    client = genai.Client(api_key=api_key)

    print(f"[uploading] {video_path}", file=sys.stderr)
    video_file = client.files.upload(file=video_path)
    while video_file.state.name == "PROCESSING":
        time.sleep(1)
        video_file = client.files.get(name=video_file.name)
    if video_file.state.name == "FAILED":
        print(f"file upload failed: {video_file.state}", file=sys.stderr)
        return 1

    print(f"[analyzing] model={MODEL_ID}", file=sys.stderr)
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=[video_file, PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SCHEMA,
            temperature=0.3,
        ),
    )

    parsed = json.loads(response.text)
    print(json.dumps(parsed, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
