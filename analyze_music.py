"""
Analyze a music clip with Gemini 3.1 Pro and emit a structured JSON timeline
aligned to vocals, beats, and musical transitions. Designed to be chainable
into the mograph pipeline (each `section` can map to a timeline clip).

Usage:
    python analyze_music.py liquidated_30s.mp3 > music_timeline.json
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
        "summary": {
            "type": "object",
            "properties": {
                "genre": {"type": "string"},
                "mood": {"type": "string"},
                "bpm_estimate": {"type": "number"},
                "time_signature": {"type": "string"},
                "key": {"type": "string"},
                "dominant_instruments": {"type": "array", "items": {"type": "string"}},
                "overall_description": {"type": "string"},
            },
            "required": ["genre", "mood", "bpm_estimate", "overall_description"],
        },
        "sections": {
            "type": "array",
            "description": "High-level song sections (intro, verse, pre-chorus, chorus, drop, breakdown, outro, etc.)",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "Start time in seconds (float)"},
                    "end": {"type": "number", "description": "End time in seconds (float)"},
                    "label": {"type": "string", "description": "intro | verse | pre_chorus | chorus | drop | bridge | breakdown | build | outro | instrumental"},
                    "energy": {"type": "number", "minimum": 0, "maximum": 1},
                    "has_vocals": {"type": "boolean"},
                    "description": {"type": "string", "description": "One sentence describing what this section sounds like"},
                    "visual_prompt": {"type": "string", "description": "A concrete motion-graphics visual prompt that matches this section's mood/energy — will feed an image/video generator"},
                },
                "required": ["start", "end", "label", "energy", "has_vocals", "description", "visual_prompt"],
            },
        },
        "beats": {
            "type": "array",
            "description": "Major downbeats and beat-change moments in seconds. Not every beat — just musically significant hits.",
            "items": {"type": "number"},
        },
        "transitions": {
            "type": "array",
            "description": "Notable transition moments (drops, breakdowns, filter sweeps, stops, risers) in seconds",
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "number"},
                    "type": {"type": "string", "description": "drop | riser | stop | filter_sweep | buildup | impact | key_change"},
                    "description": {"type": "string"},
                },
                "required": ["time", "type", "description"],
            },
        },
        "vocal_events": {
            "type": "array",
            "description": "Vocal phrases with timing. Include lyric text if intelligible; otherwise describe the vocal performance.",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "lyric_or_description": {"type": "string"},
                    "delivery": {"type": "string", "description": "sung | rapped | spoken | chanted | ad_lib | harmonized"},
                    "intensity": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["start", "end", "lyric_or_description", "delivery", "intensity"],
            },
        },
    },
    "required": ["summary", "sections", "beats", "transitions", "vocal_events"],
}

PROMPT = """You are a music analyst preparing a structured timeline for a generative motion-graphics video pipeline.

Analyze the entire attached audio clip with second-level (ideally 0.1s-level) precision. Produce:

1. A `summary` with genre, mood, BPM estimate, time signature, key, dominant instruments.
2. `sections` — contiguous song sections (intro, verse, chorus, drop, etc.) covering the full duration with no gaps. For each section include an `energy` 0–1 value and a concrete `visual_prompt` a motion-graphics artist could feed to an image/video generator. Visual prompts should match the section's energy and mood — quiet intro = sparse/atmospheric; drop = explosive/saturated.
3. `beats` — timestamps (seconds) of musically significant downbeats and beat-shift moments. Don't list every single beat; pick the ones that matter for visual cuts.
4. `transitions` — drops, risers, stops, filter sweeps, impacts, key changes with timestamps.
5. `vocal_events` — every vocal phrase with start/end timestamps. Transcribe lyrics when intelligible; otherwise describe delivery. Mark delivery style and intensity.

All timestamps MUST be within the actual audio duration. Be precise and consistent — downstream code cuts video clips on these times."""


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: analyze_music.py <audio_file>", file=sys.stderr)
        return 2

    audio_path = sys.argv[1]
    if not os.path.exists(audio_path):
        print(f"file not found: {audio_path}", file=sys.stderr)
        return 2

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY not set", file=sys.stderr)
        return 2

    client = genai.Client(api_key=api_key)

    print(f"[uploading] {audio_path}", file=sys.stderr)
    audio_file = client.files.upload(file=audio_path)

    while audio_file.state.name == "PROCESSING":
        time.sleep(1)
        audio_file = client.files.get(name=audio_file.name)
    if audio_file.state.name == "FAILED":
        print(f"file upload failed: {audio_file.state}", file=sys.stderr)
        return 1

    print(f"[analyzing] model={MODEL_ID}", file=sys.stderr)
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=[audio_file, PROMPT],
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
