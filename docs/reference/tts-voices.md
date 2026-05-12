# TTS & Voices

## Technology

Google Gemini 3.1 Flash TTS (model ID `gemini-3.1-flash-tts-preview`) — deeply multimodal, understands the full script context for natural, contextually-appropriate narration. Outputs PCM 24kHz 16-bit mono, all output is SynthID-watermarked.

Pass `--tts-model gemini-2.5-flash-preview-tts` or set `defaults.tts.model = "gemini-2.5-flash-tts"` in a timeline to fall back to 2.5.

## Usage

```bash
# Use a specific Gemini voice
python pipeline.py --timeline-file my-timeline.json --voice Puck --stage final

# Default voice (Kore)
python pipeline.py --timeline-file my-timeline.json --stage final

# List available voices
python pipeline.py --list-voices
```

## Audio tags (3.1 only)

3.1 supports 200+ inline audio tags written in square brackets directly in the text. Examples:

```
[whispers] I have a secret. [laughs] You'll never guess.
[excited] We did it! [sighs] What a day.
[sarcastic] Sure, that's exactly what I wanted.
```

Tag names like `[amazed] [crying] [curious] [excited] [sighs] [gasp] [giggles] [laughs] [mischievously] [panicked] [sarcastic] [serious] [shouting] [tired] [trembling] [whispers]` are supported, plus arbitrary custom tags like `[like a cartoon dog]` or `[one painfully slow word at a time]`. For longer-form style control, write a Director's Notes / Audio Profile block in the `voice_prompt` field.

## Available Voices

30 preset Gemini voices: Kore (default), Puck, Charon, Aoede, Fenrir, Zubenelgenubi, and 24 more.

Use `python pipeline.py --list-voices` to see the full list.
