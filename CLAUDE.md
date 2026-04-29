# explainer-mograph

Video generation pipeline that takes timeline JSON files and produces narrated explainer videos with motion graphics visuals.

## Quick Start

```bash
# Run full pipeline from a timeline file
python pipeline.py --timeline-file my-timeline.json --stage final

# Dry run (show execution plan without running)
python pipeline.py --timeline-file my-timeline.json --dry-run

# Mock mode (test without API calls — uses fixtures for image/video/TTS)
python pipeline.py --mock --timeline-file my-timeline.json --stage final
```

## Pipeline Stages

- **images** — Generate images from timeline clip prompts
- **videos** — Generate videos from images
- **final** — Assemble final video with narration audio overlay

Each stage can be run independently with `--resume-dir <run_dir>`.

## Directory Structure

- `pipeline.py` — Main pipeline orchestrator (CLI entry point, stays at root)
- `timeline/` — Timeline format: parser, validator, DAG builder, executor, and stage generators
- `generation/` — Image and video generation (Replicate Nano Banana Pro, GPT Image 2, Seedance; Gemini Nano Banana 2 direct)
- `tts/` — Text-to-speech, transcription, audio processing (Gemini TTS, ElevenLabs, Deepgram)
- `shared/` — Common utilities (media processing, Replicate client, helpers)
- `cloudrun/` — Cloud Run HTTP API deployment (FastAPI server, GCS storage)
- `scripts/` — Operational scripts (deploy, asset sync)
- `docs/` — Documentation (CLI reference, pipeline modes, deployment, timeline format, etc.)
- `docs/timeline/` — Timeline format docs (examples, schema, model reference, patterns)
- `assets/` — Project-specific reference images (consolidated)
- `runs/` — Pipeline output directory (gitignored)
- `tests/` — Test fixtures

## Key Conventions

- All generation API calls go through `shared/replicate_client.py` (thread-safe with thread-local storage)
- Mock mode (`--mock`) uses fixtures from `tests/fixtures/` for image/video and mock audio for TTS (no real API calls)
- Timeline format is the only input format — see `timeline/` package for the implementation

## Timeline Format

The timeline JSON format is the declarative input for the video pipeline. Documentation is layered:

1. **Examples** — `docs/timeline/examples/` — Copy and modify working timeline files
2. **Format Reference** — `docs/timeline/format-reference.md` — Complete field-by-field schema docs
3. **Model Reference** — `docs/timeline/models.md` — Per-model parameters, constraints, and costs
4. **Patterns** — `docs/timeline/patterns.md` — Advanced workflows (chaining, exploration, mixing)

JSON Schema for programmatic validation: `docs/timeline/timeline.schema.json`

## See Also

See `docs/` for detailed documentation on CLI usage, pipeline modes, deployment, and architecture.
