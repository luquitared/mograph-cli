# TTS & Voices

## Technology

Google Gemini 2.5 Flash/Pro TTS -- deeply multimodal, understands the full script context for natural, contextually-appropriate narration.

## Usage

```bash
# Use a specific Gemini voice
python pipeline.py --timeline-file my-timeline.json --voice Puck --stage final

# Default voice (Kore)
python pipeline.py --timeline-file my-timeline.json --stage final

# List available voices
python pipeline.py --list-voices
```

## Available Voices

29 preset Gemini voices available including Kore (default), Puck, Charon, Aoede, Fenrir, and more.

Use `python pipeline.py --list-voices` to see the full list.
