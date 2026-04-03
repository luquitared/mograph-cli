# Inspecting Runs & Previous Generations

## Where Runs Live

All pipeline outputs go to GCS: `gs://eternal-skyline-475200-q6-explainer-outputs/`

Run directories are named either:
- **From CLI**: `<slugified-title>-<timestamp>/` (e.g., `my-video-20251215-143546/`)
- **From API**: `<uuid>/` (e.g., `e8991380-034d-4cc1-9226-0dcae811745d/`)

## Listing Runs

```bash
# List all runs
gsutil ls gs://eternal-skyline-475200-q6-explainer-outputs/

# List contents of a specific run
gsutil ls gs://eternal-skyline-475200-q6-explainer-outputs/<run-id>/
```

## Run Directory Structure

```
<run-id>/
├── images/                  # Generated images
├── videos/                  # Generated video clips
├── audio/                   # TTS narration per scene (.mp3)
└── final/
    ├── final.mp4            # Narration only
    └── final_with_sfx.mp4   # Narration + sound effects
```

## Downloading Videos

```bash
# Download final video
gsutil cp gs://eternal-skyline-475200-q6-explainer-outputs/<run-id>/final/final_with_sfx.mp4 ./

# Download all outputs for a run
gsutil -m cp -r gs://eternal-skyline-475200-q6-explainer-outputs/<run-id>/ ./local-output/

# Download just images
gsutil -m cp gs://eternal-skyline-475200-q6-explainer-outputs/<run-id>/images/* ./images/
```
