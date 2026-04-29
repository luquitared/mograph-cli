#!/usr/bin/env python3
"""Use Gemini to extract a structured style description from a reference video.

Usage:
    python scripts/style_describe.py <source_video.mp4> <output_json>
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
        "name": {"type": "string", "description": "Short evocative name for the style (3-6 words)"},
        "tagline": {"type": "string", "description": "One-sentence pitch — what the style is and what kind of content it suits"},
        "medium": {"type": "string", "description": "What is this — 3D render, hand-drawn anime, claymation, photo, etc"},
        "era_reference": {"type": "string", "description": "What era or specific reference does this evoke (e.g. PS1 1995-2000, early 2010s anime, 1970s film)"},
        "color_palette": {
            "type": "array",
            "items": {"type": "string"},
            "description": "5-8 colors that dominate the frame, with usage notes (e.g. 'deep navy night sky', 'vivid neon red on signage')",
        },
        "linework_and_texture": {"type": "string", "description": "Polygon count, texture resolution, anti-aliasing, edge treatment"},
        "lighting": {"type": "string", "description": "Light sources, contrast, atmosphere, time of day"},
        "composition": {"type": "string", "description": "Camera angles, framing, aspect ratio, motion (static / pan / handheld)"},
        "mood": {"type": "string", "description": "Emotional register — nostalgic, eerie, playful, gritty, etc"},
        "subjects_in_source": {"type": "string", "description": "What is actually shown in the source — environments, characters, products, etc"},
        "what_to_keep": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific visual elements to PRESERVE if generating new content in this style",
        },
        "what_to_avoid": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Things that would break the style (e.g. 'modern PBR shading', 'hand-drawn line art')",
        },
        "prompt_template": {
            "type": "string",
            "description": "A reusable STYLE: prompt suffix to paste into image/video gen prompts. Should be concrete and pasteable, not vague.",
        },
    },
    "required": [
        "name", "tagline", "medium", "era_reference", "color_palette",
        "linework_and_texture", "lighting", "composition", "mood",
        "subjects_in_source", "what_to_keep", "what_to_avoid", "prompt_template",
    ],
}

PROMPT = """Watch this video and produce a structured style description that another image/video generator could USE to recreate the look. Be concrete — use specific render terms, specific color descriptions, specific era references. Avoid vague adjectives like "stylized" or "unique" without further detail.

Pay special attention to:
- The rendering era / engine vibe (early 3D? hand-drawn? CGI? live action?)
- Polygon count, texture resolution, anti-aliasing presence — these are load-bearing in style identification
- Whether this looks like real footage or generated/rendered content
- The aspect ratio and how it influences composition
- Any visual treatments (CRT scanlines, film grain, dithering, etc.)

The `prompt_template` field will be pasted directly into prompts for image and video generation models — write it as a concrete STYLE: clause that captures the look in 2-4 sentences."""


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: style_describe.py <source_video.mp4> <output_json>", file=sys.stderr)
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
