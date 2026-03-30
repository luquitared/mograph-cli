# Inspecting Runs & Previous Generations

## Where Runs Live

All pipeline outputs go to GCS: `gs://eternal-skyline-475200-q6-explainer-outputs/`

Run directories are named either:
- **From script**: `<slugified-title>-<timestamp>/` (e.g., `my-video-20251215-143546/`)
- **From API**: `<uuid>/` (e.g., `e8991380-034d-4cc1-9226-0dcae811745d/`)

## Listing Runs

```bash
# List all runs
gsutil ls gs://eternal-skyline-475200-q6-explainer-outputs/

# List contents of a specific run
gsutil ls gs://eternal-skyline-475200-q6-explainer-outputs/<run-id>/

# Find runs that have metrics (completed runs)
gsutil ls gs://eternal-skyline-475200-q6-explainer-outputs/*/run_metrics.json
```

## Run Directory Structure

```
<run-id>/
├── run_config.json          # Pipeline settings (model, voice, timing mode, etc.)
├── run_metrics.json         # Stage durations + cost breakdown (added Dec 2025+)
├── script.json              # Generated or input script
├── batch.json               # Batch image generation config
├── visual_outputs.json      # Visual output metadata
├── video_jobs.json          # Video generation job details
├── images/                  # Generated images per scene
├── videos/                  # Generated video clips
├── audio/                   # TTS narration per scene (.mp3 + .timestamps.json)
├── videos_adjusted/         # Duration-adjusted videos
├── videos_with_audio/       # Videos with overlaid narration
├── videos_images_only/      # Slideshow versions (static image + narration)
└── final/
    ├── final.mp4            # Narration only
    ├── final_with_sfx.mp4   # Narration + Veo sound effects
    └── final_images_only.mp4 # Slideshow version
```

## Viewing Pipeline Stats

### run_metrics.json

Contains stage durations, total time, and cost breakdown:

```bash
gsutil cat gs://eternal-skyline-475200-q6-explainer-outputs/<run-id>/run_metrics.json | python3 -m json.tool
```

Example output:
```json
{
  "total_duration_seconds": 578.01,
  "stages": {
    "images": { "duration_seconds": 205.06 },
    "videos": { "duration_seconds": 82.2 },
    "final":  { "duration_seconds": 290.76 }
  },
  "costs": {
    "total_usd": 8.4,
    "by_category": {
      "images": 1.2,
      "videos": 7.2
    }
  }
}
```

**Note**: `run_metrics.json` was added in Dec 2025. Older runs won't have it.

### Typical Performance (8-scene video, Veo Fast, 6s clips)

| Stage | Duration | What's happening |
|-------|----------|-----------------|
| Images | 200-280s | Generating 8 images via Replicate |
| Videos | 45-150s | Generating 8 video clips via Veo (concurrent) |
| Final | 110-450s | TTS per scene + FFmpeg assembly |
| **Total** | **6-14 min** | End to end |

Cost: ~$8-9 for an 8-scene video (images $1.20 + videos $7.20).

### run_config.json

Shows pipeline settings used:

```bash
gsutil cat gs://eternal-skyline-475200-q6-explainer-outputs/<run-id>/run_config.json | python3 -m json.tool
```

Key fields: `video_model`, `video_seconds`, `start_frame_mode`, `voice`, `completed_stages`.

### script.json

Shows the generated/input script with all scenes and prompts:

```bash
gsutil cat gs://eternal-skyline-475200-q6-explainer-outputs/<run-id>/script.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
scenes = d.get('scenes', [])
print(f'Title: {d.get(\"script_title\", \"?\")}')
print(f'Scenes: {len(scenes)}')
for s in scenes:
    words = len(s.get('narrator', '').split())
    clips = len(s.get('visuals', []))
    print(f'  Scene {s[\"scene_number\"]}: {words} words, {clips} clip(s) — {s.get(\"narrator\", \"\")[:80]}')
"
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

## Quick Summary Script

Summarize multiple runs at once:

```bash
for run_id in <run1> <run2> <run3>; do
  echo "=== $run_id ==="
  gsutil cat "gs://.../$run_id/run_metrics.json" 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f\"  Total: {d.get('total_duration_seconds', '?')}s | Cost: \${d.get('costs', {}).get('total_usd', '?')}\")
for stage, info in d.get('stages', {}).items():
    print(f\"  {stage}: {info.get('duration_seconds', '?')}s\")
" 2>/dev/null || echo "  (no metrics)"
done
```

