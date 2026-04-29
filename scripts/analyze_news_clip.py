#!/usr/bin/env python3
"""Use Gemini to extract per-character speech timestamps from a news clip.

Usage: analyze_news_clip.py <video_file>
Prints JSON: {speakers: [{name, start, end, line}, ...]}
"""

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
        "speakers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Maya, Trip, or FAQ-9000 — pick the closest match",
                    },
                    "start": {"type": "number", "description": "speech start in seconds"},
                    "end": {"type": "number", "description": "speech end in seconds"},
                    "line": {"type": "string", "description": "transcribed line of dialogue"},
                    "voice_notes": {
                        "type": "string",
                        "description": "short description of voice character (tone, pitch, accent, robotic processing, etc.)",
                    },
                },
                "required": ["name", "start", "end", "line", "voice_notes"],
            },
        },
    },
    "required": ["duration_sec", "speakers"],
}

PROMPT = """Watch this short news-show clip and identify every spoken line.

The cast:
- Maya: sharp female anchor, dark bob, blue blazer
- Trip: blonde male himbo co-host, charcoal suit, pink tie
- FAQ-9000: a deadpan tin robot, monotone robotic voice

For each spoken line, return:
- speaker name (Maya / Trip / FAQ-9000)
- start and end timestamp (seconds, precise to ~0.1s)
- the transcribed line
- short voice notes (timbre, energy, processing) so we can re-prompt with consistent voices later

Timestamps must be within the actual clip duration. Be precise — downstream code will cut audio on these times.
"""


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: analyze_news_clip.py <video_file>", file=sys.stderr)
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
            temperature=0.2,
        ),
    )

    parsed = json.loads(response.text)
    print(json.dumps(parsed, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
