# Pipeline Modes

## Mode Summary

| Mode | Input | Best For |
|------|-------|----------|
| **Script Mode** (default) | Full script JSON with scenes | Full creative control |
| **TTS-Only Mode** | Narration text + `--tts-only` | Generate audio first, design script manually |
| **Voice Mode** | Voice recording + `--voice-file` | Your own narration |

## 1. Script Mode (default)

Provide a complete script JSON with scenes, narration, and visual prompts:

```bash
python pipeline.py \
  --script-file my-complete-script.json \
  --main-ref images/main-ref-images/blank_white_9x16.png \
  --stage final
```

Flow: Script loaded -> images -> videos -> TTS per scene -> audio reconciled with video -> final assembly.

## 2. TTS-Only Mode

Generate TTS and timestamps, then stop. Design your script manually with Claude, then resume:

```bash
python pipeline.py \
  --script-file my-narration-script.json \
  --tts-only

# Design script using timestamps, then resume:
python pipeline.py \
  --resume-dir runs/my-video-20251209-142627 \
  --stage final
```

## 3. Voice Mode (Voice-to-Video)

Create videos from your own voice recordings:

```bash
python pipeline.py \
  --voice-file my-narration.mp3 \
  --main-ref images/main-ref-images/blank_white_9x16.png \
  --style-notes "Minimalist tech aesthetic, blue and white" \
  --stage final
```

Flow: Deepgram transcription (word-level timestamps) -> segments into scenes -> images -> videos -> original audio sliced per scene -> final assembly.

Tips: Speak clearly with natural pauses between topics. The AI uses pauses to create logical scene breaks.

### Transcription Module

```bash
python transcribe.py my-audio.mp3          # Basic transcription
python transcribe.py my-audio.mp3 --llm-format  # LLM-friendly output
```

## Start Frame Modes (`--start-frame-mode`)

| Mode | How It Works | Parallel? | Best For |
|------|-------------|-----------|----------|
| `animate` (default) | Each scene's image is the start frame, no end frame constraint | Yes | Creative freedom for the model |
| `transition` | Previous scene's image is the start frame | Yes | Visual continuity between scenes |
| `reference` | Always uses blank reference as start frame | Yes | Each scene starts fresh |
| `sequential` | Extracts last frame from previous video | No (slower) | Seamless video-to-video transitions |
