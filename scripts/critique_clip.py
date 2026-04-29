#!/usr/bin/env python3
"""Use Gemini to critique a generated clip against its intended brief.

Usage: critique_clip.py <video_file> <brief>
  brief: short string describing what the clip was supposed to do
Prints structured JSON critique.
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
        "visuals": {
            "type": "string",
            "description": "What's actually shown on screen, beat by beat",
        },
        "audio": {
            "type": "string",
            "description": "What's heard — dialogue (transcribe verbatim), music, SFX",
        },
        "characters_visible": {
            "type": "boolean",
            "description": "Whether any people/characters appear on camera at any point",
        },
        "voice_consistency": {
            "type": "string",
            "description": "If a reference voice was specified (e.g. 'Maya, sharp anchor'), assess match: which voice was used, does it sound like the brief asked for, or is it generic?",
        },
        "brief_followed": {
            "type": "string",
            "description": "Did the clip follow the brief? List any deviations",
        },
        "quality_issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Notable visual or audio defects (artifacting, lip sync off, weird timing, etc.)",
        },
        "overall_score": {
            "type": "integer",
            "description": "1-10 score of how well this clip executes the brief",
        },
    },
    "required": [
        "duration_sec", "visuals", "audio", "characters_visible",
        "voice_consistency", "brief_followed", "quality_issues", "overall_score",
    ],
}


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: critique_clip.py <video_file> <brief>", file=sys.stderr)
        return 2

    video_path = sys.argv[1]
    brief = sys.argv[2]
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

    prompt = f"""Watch this clip and critique it against the brief below.

BRIEF:
{brief}

Be concrete and honest. If the brief said "no characters" and a character appears, flag it.
If the brief specified a particular voice, listen carefully and judge whether the voice
matches that description vs. sounds like a generic AI voice. Transcribe dialogue verbatim.
Note any visual or audio defects.
"""

    print(f"[analyzing] model={MODEL_ID}", file=sys.stderr)
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=[video_file, prompt],
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
