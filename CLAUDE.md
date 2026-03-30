# explainer-mograph

Video generation pipeline that takes scripts (or voice recordings) and produces narrated explainer videos with motion graphics visuals.

## Quick Start

```bash
# Script mode (default — pre-written script JSON)
python pipeline.py --script-file script.json --stage final

# TTS-only mode (generate narration audio, then stop)
python pipeline.py --tts-only --script-file narration.json --stage final

# Voice mode (use existing voice recording as narration)
python pipeline.py --voice-file recording.mp3

# Mock mode (test without API calls — uses fixtures for image/video, still calls real Gemini TTS)
python pipeline.py --mock --stage final --script-file script.json
```

## Pipeline Stages

- **images** — Generate images from script visuals (Replicate Nano Banana Pro)
- **videos** — Generate videos from images (Veo 3.1)
- **final** — Assemble final video with narration audio overlay

Each stage can be run independently with `--resume-dir <run_dir>`.

## Directory Structure

- `pipeline.py` — Main pipeline orchestrator (CLI entry point, stays at root)
- `generation/` — Image and video generation (Replicate Nano Banana, Veo)
- `tts/` — Text-to-speech, transcription, audio processing (Gemini TTS, ElevenLabs, Deepgram)
- `pipeline/` — Script-to-batch conversion (script_to_batch.py)
- `shared/` — Common utilities (media processing, Replicate client, helpers)
- `cloudrun/` — Cloud Run HTTP API deployment (FastAPI server, GCS storage)
- `batch/` — Batch processing client for Cloud Run
- `scripts/` — Operational scripts (deploy, asset sync)
- `docs/` — Documentation (CLI reference, pipeline modes, deployment, etc.)
- `assets/` — Project-specific reference images (consolidated)
- `runs/` — Pipeline output directory (gitignored)
- `tests/` — Test fixtures

## Key Conventions

- `pipeline.py` (file) and `pipeline/` (package) coexist — pipeline.py imports from the package via `from pipeline.script_to_batch import ...`
- `cloudrun/server.py` loads pipeline.py via importlib (path-based, not name-based) to avoid the name collision
- All generation API calls go through `shared/replicate_client.py` (thread-safe with thread-local storage)
- Mock mode (`--mock`) uses fixtures from `tests/fixtures/` for image/video and mock audio for TTS (no real API calls)

## See Also

See `docs/` for detailed documentation on CLI usage, pipeline modes, deployment, and architecture.
