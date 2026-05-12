# Mograph CLI

Create videos using AI paired with Claude Code / Codex

## Important tips

- **TTS / explainer / pre-recorded voice over** → see [`docs/workflows/narration-explainer/`](docs/workflows/narration-explainer/)
- For TTS or seedance voices, one good rule of thumb is **2.5 WPS** (so it fits in the video duration)
- Replicate seedance silently truncates the prompt past **2,000 characters**
- **Creating references / assets** → see [`docs/workflows/character-asset/`](docs/workflows/character-asset/), or scaffold a project + ref manifest with `python scripts/init_project.py "Project Name"`. Published asset/style/format packs land via `--from-pack <id>` (see [`docs/workflows/style-rip/`](docs/workflows/style-rip/) and [`docs/workflows/format-rip/`](docs/workflows/format-rip/))
- Seedance is still decently unstable. Past 15s (multi-clip), the model has no information about other clips — reference inputs are your friend

## Multi-clip consistency

Seedance has zero memory between generations. Anything that needs to repeat across ≥2 clips — a character, multiple characters, a voice, a location, an outfit, a lighting setup, a visual style — has to be bound explicitly via reference images or reference audios. If you don't bind it, it will drift.

- **Prefer one ≤15s clip over multiple shorter ones.** A single clip preserves all of this for free. Only split when a hard constraint forces it: per-section text overlays that change mid-video, per-section reference images that conflict, or beat structures that need different camera framings.
- **When multi-clip is required, identify what needs to repeat, then bind it.** Scale up only as far as you actually need:
  - **Style** — minimum bar: a moodboard (3–5 frames in the target aesthetic) as `reference_images` on every clip.
  - **Character (single or recurring cast)** — a character reference sheet generated once and passed on every clip the character is in.
  - **Voice** — extract 5–10s of WAV from the first generated clip, pass as `reference_audios` thereafter (E006 requires `reference_images` too).
  - **Location / set** — an establishing image of the location passed as a reference on every clip set there.
- **Some video types tolerate inconsistency.** Explainer videos with a different visual per beat are often fine without binding — each beat is its own world. Confirm with the user before assuming consistency is needed.

Each workflow has its own approach for this — read the workflow's `CLAUDE.md`. If a workflow is silent on consistency, you still need to do it; silence doesn't mean optional.

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

- `pipeline.py` — main pipeline orchestrator (CLI entry point, stays at root)
- `timeline/` — timeline format: parser, validator, DAG builder, executor, stage generators
- `generation/` — image and video generation (Replicate Nano Banana Pro, GPT Image 2, Seedance; Gemini Nano Banana 2 direct)
- `tts/` — text-to-speech, transcription, audio processing (Gemini TTS, ElevenLabs, Deepgram)
- `shared/` — common utilities (media processing, Replicate client, helpers)
- `cloudrun/` — Cloud Run HTTP API (FastAPI server, GCS storage)
- `deployment/` — deploy script + Cloud Run deployment docs
- `scripts/` — operational scripts (`init_project.py`, `run.py`, asset sync, etc.)
- `assets/` — project-specific reference images
- `runs/` — pipeline output directory (gitignored)
- `tests/` — test fixtures
- `docs/workflows/` — recipes per video type (narration, news, music, style-rip, format-rip, character, video-clone)
- `docs/reference/` — CLI, pipeline modes, TTS voices, run inspection, e2e testing, timeline format + models

## Key Conventions

- All generation API calls go through `shared/replicate_client.py` (thread-safe with thread-local storage)
- Mock mode (`--mock`) uses fixtures from `tests/fixtures/` for image/video and mock audio for TTS (no real API calls)
- Timeline format is the only input format — see `timeline/` package for the implementation

## Timeline Format

The timeline JSON format is the declarative input for the video pipeline.

- **Format Reference** — [`docs/reference/timeline/format-reference.md`](docs/reference/timeline/format-reference.md) — complete field-by-field schema docs
- **Model Reference** — [`docs/reference/timeline/models.md`](docs/reference/timeline/models.md) — per-model parameters, constraints, costs
- **Workflow examples** — every folder under `docs/workflows/` has its own `examples/` of working timelines

## See Also

- [`docs/workflows/`](docs/workflows/) — pick a recipe matching the kind of video the user wants
- [`docs/reference/`](docs/reference/) — deeper docs on CLI, pipeline modes, TTS voices, timeline format
- [`deployment/`](deployment/) — Cloud Run deployment
