# E2E Pipeline Tests

Run the full pipeline for real (no mock) using a timeline JSON file.

## Prerequisites

- `.env` file at project root with: `REPLICATE_API_TOKEN`, `GOOGLE_API_KEY`
- All agents must source `.env` and export keys before running pipeline commands
- Test timeline: `docs/timeline/examples/simple-explainer.json` (2-scene photosynthesis explainer)

## Full Pipeline Run

Single command, runs all stages end-to-end.

```bash
source .env && export REPLICATE_API_TOKEN GOOGLE_API_KEY
python pipeline.py --timeline-file docs/timeline/examples/simple-explainer.json --stage final
```

Timeout: 10 minutes. Produces `final/` directory with final video output.

## Mock Mode (no API calls)

```bash
python pipeline.py --timeline-file docs/timeline/examples/simple-explainer.json --mock --stage final
```

Uses fixtures from `tests/fixtures/` for image/video and mock audio for TTS.

## Resume from Prior Run

```bash
python pipeline.py --timeline-file docs/timeline/examples/simple-explainer.json --resume-dir <RUN_DIR> --stage final
```

Skips already-completed stages and resumes from where the previous run stopped.

## Expected Results

Each run produces in its run directory:
- `images/` — Generated image assets
- `videos/` — Generated video clips
- `audio/` — Generated TTS audio
- `final/` — Assembled final video output(s)

**Important:** Each agent must print the full absolute path of every output file when reporting results.

## Known Issues

- Replicate image generation and Veo video generation may retry on rate limits — this is normal.
- Mock mode uses local test fixtures instead of calling real APIs.
