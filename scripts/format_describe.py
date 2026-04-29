#!/usr/bin/env python3
"""Use Gemini to extract a structured FORMAT description from a reference video.

Different from style_describe.py — that captures the visual *look*. This
captures the *structural template*: beats, audio events, text overlays,
camera moves, archetype, and what's swappable vs fixed for re-filling
with new content.

Usage:
    python scripts/format_describe.py <source_video.mp4> <output_json>
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
        "archetype": {
            "type": "string",
            "description": "What kind of format is this — e.g. 'POV reaction trope', 'setup-punchline meme', 'tutorial', 'vlog moment', 'before/after', 'expectation vs reality'. Be specific to what the video does structurally."
        },
        "duration_sec": {"type": "number"},
        "aspect_ratio": {"type": "string", "description": "Source aspect ratio (9:16, 16:9, 1:1)"},
        "summary": {"type": "string", "description": "One-sentence structural summary independent of subject"},
        "beats": {
            "type": "array",
            "description": "Time-ordered structural beats. Each beat is a discrete moment with its own purpose.",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "label": {"type": "string", "description": "Short structural label — e.g. 'setup', 'establishing shot', 'text overlay enters', 'punchline reaction', 'cut to bed'"},
                    "what_happens": {"type": "string", "description": "What actually occurs visually + audibly in this beat"},
                    "audio_event": {"type": "string", "description": "Notable sound at this beat (sfx ding, music drop, dialogue, silence)"},
                    "text_overlay": {"type": "string", "description": "Text on screen during this beat (verbatim) or empty if none"},
                    "camera": {"type": "string", "description": "Shot type / framing / movement"}
                },
                "required": ["start", "end", "label", "what_happens", "audio_event", "text_overlay", "camera"]
            }
        },
        "persistent_text_overlays": {
            "type": "array",
            "description": "Text that stays on screen for the whole video or most of it",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "position": {"type": "string", "description": "top / center / bottom / etc"},
                    "style": {"type": "string", "description": "Font weight, color, stroke, shadow"}
                },
                "required": ["text", "position", "style"]
            }
        },
        "audio_design": {
            "type": "object",
            "properties": {
                "music": {"type": "string", "description": "Music style and behavior, or 'none'"},
                "key_sfx": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "timestamp": {"type": "number"},
                            "sfx": {"type": "string", "description": "Description of the sound effect"},
                            "load_bearing": {"type": "boolean", "description": "Whether removing this sfx would break the format"}
                        },
                        "required": ["timestamp", "sfx", "load_bearing"]
                    }
                },
                "dialogue": {"type": "string", "description": "Spoken words verbatim, or 'none'"}
            },
            "required": ["music", "key_sfx", "dialogue"]
        },
        "format_signature": {
            "type": "string",
            "description": "What makes this format recognizable. The 1-2 elements that, if removed, would make this no longer 'this format'."
        },
        "remixable": {
            "type": "object",
            "properties": {
                "swappable": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Elements that can be replaced without breaking the format (subject, text content, character, setting, visual style)"
                },
                "fixed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Elements that must be preserved (timing, beat sequence, sfx triggers, camera moves)"
                }
            },
            "required": ["swappable", "fixed"]
        },
        "remix_template": {
            "type": "string",
            "description": "A reusable format template described as instructions for someone re-filling it with different content. Should be 3-6 sentences and concrete."
        }
    },
    "required": [
        "archetype", "duration_sec", "aspect_ratio", "summary", "beats",
        "persistent_text_overlays", "audio_design", "format_signature",
        "remixable", "remix_template"
    ]
}

PROMPT = """Watch this video and extract its FORMAT — the structural template, not the visual style. I'm looking for the kind of analysis that would let someone re-fill this format with different content (different subject, different text, different visuals) and still have it read as the same trope/format.

Pay special attention to:
- Time-ordered beats (when does each structural moment start and end)
- Text overlays — both persistent (stays whole video) and beat-specific (appears at a moment)
- Sound effects with their timestamps and whether they're load-bearing (a "ding" at a reveal beat IS the format; ambient room tone is not)
- Camera moves and shot types per beat
- The format archetype — what category of internet video this is (reaction, before/after, expectation-vs-reality, tutorial, etc.)
- What's load-bearing vs swappable — the goal is to enable remixing

Output the `remix_template` field as concrete instructions someone could follow to make a new video in this format. Avoid vague language.

For audio, transcribe dialogue verbatim and describe sfx specifically (not "a sound" but "iMessage incoming notification ding")."""


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: format_describe.py <source_video.mp4> <output_json>", file=sys.stderr)
        return 2

    src = sys.argv[1]
    out = sys.argv[2]
    if not os.path.exists(src):
        print(f"not found: {src}", file=sys.stderr)
        return 2

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY not set", file=sys.stderr)
        return 2

    client = genai.Client(api_key=api_key)
    print(f"[uploading] {src}", file=sys.stderr)
    f = client.files.upload(file=src)
    while f.state.name == "PROCESSING":
        time.sleep(1)
        f = client.files.get(name=f.name)
    if f.state.name == "FAILED":
        print(f"upload failed: {f.state}", file=sys.stderr)
        return 1

    print(f"[analyzing] model={MODEL_ID}", file=sys.stderr)
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=[f, PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SCHEMA,
            temperature=0.2,
        ),
    )

    parsed = json.loads(response.text)
    with open(out, "w") as fh:
        json.dump(parsed, fh, indent=2)
    print(f"[OK] {out}")
    print(json.dumps(parsed, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
