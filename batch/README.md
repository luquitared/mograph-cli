# Batch Cloud Run Script

Run multiple video generation jobs on Cloud Run in parallel. This script handles uploading scripts and reference images to GCS, submitting jobs to Cloud Run, and downloading results.

## Quick Start

```bash
# From the project root
python batch/batch_cloudrun.py \
  --config batch/batch_config.json \
  --scripts-dir ./scripts \
  --output-dir ./output
```

## Setup

### 1. Create Config File

Copy the example config and fill in your values:

```bash
cp batch/batch_config.example.json batch/batch_config.json
```

Edit `batch_config.json`:

```json
{
  "service_url": "https://explainer-mograph-YOUR_PROJECT.us-central1.run.app",
  "output_bucket": "YOUR_PROJECT-explainer-outputs",
  "service_account_key": "./path-to-service-account-key.json",
  "defaults": {
    "video_model": "fast",
    "video_seconds": 6,
    "start_frame_mode": "animate",
    "stage": "final",
    "concurrency": 5,
    "voice": "Rachel",
    "enable_text_verification": false
  }
}
```

| Field | Description |
|-------|-------------|
| `service_url` | Your Cloud Run service URL |
| `output_bucket` | GCS bucket for outputs (without `gs://` prefix) |
| `service_account_key` | Path to service account JSON key file |
| `defaults` | Default pipeline settings (can be overridden per-script) |

### 2. Prepare Scripts

Create a folder with your script JSON files:

```
scripts/
  video1.json
  video2.json
  video3.json
```

Each script should define `reference_images` with paths relative to the script location:

```json
{
  "script_title": "My Explainer Video",
  "reference_images": [
    "images/references/brand-style.png",
    "images/references/logo.png"
  ],
  "scenes": [
    {
      "scene_number": 1,
      "scene_type": "Hook",
      "narrator": "Your narration text here...",
      "visuals": [
        {
          "concept_name": "opening_visual",
          "image_prompt": "Use the same style as the given moodboard image. Description of the visual...",
          "animation_prompt": "Description of how it animates..."
        }
      ]
    }
  ]
}
```

### 3. Add Reference Images

Place reference images where your scripts expect them:

```
scripts/
  video1.json
  images/
    references/
      brand-style.png
      logo.png
```

The script will automatically:
1. Find `reference_images` paths in each script
2. Upload them to GCS
3. Pass them to Cloud Run for image generation

## Usage

### Basic Usage

```bash
python batch/batch_cloudrun.py \
  --config batch/batch_config.json \
  --scripts-dir ./scripts \
  --output-dir ./output
```

### All Options

```bash
python batch/batch_cloudrun.py \
  --config CONFIG_FILE         # Path to batch_config.json
  --scripts-dir SCRIPTS_DIR    # Directory containing script JSON files
  --output-dir OUTPUT_DIR      # Directory to download results to
  --concurrency N              # Max parallel jobs (default: from config)
  --dry-run                    # Validate without running
```

### Per-Script Overrides

You can override defaults in individual scripts using `pipeline_config`:

```json
{
  "script_title": "High Quality Video",
  "reference_images": ["images/style.png"],
  "pipeline_config": {
    "video_model": "quality",
    "video_seconds": 8,
    "voice": "Antoni"
  },
  "scenes": [...]
}
```

## Output Structure

After running, results are downloaded to your output directory:

```
output/
  video1/
    script.json          # Copy of input script
    batch.json           # Batch generation config
    run_config.json      # Pipeline run configuration
    images/
      scene1_*.png       # Generated images
      scene2_*.png
    videos/
      *.mp4              # Generated video clips
    audio/
      scene01.mp3        # Generated narration
    final/
      final.mp4          # Final assembled video (narration only)
      final_with_sfx.mp4 # Final video with Veo sound effects
    batch_metrics.json   # Timing and status info
  video2/
    ...
  batch_metrics.json     # Overall batch metrics
```

## Reference Images

Reference images control the visual style of generated images. The image generation model uses them as style/content references.

### How It Works

1. Define `reference_images` in your script JSON (relative paths)
2. `batch_cloudrun.py` uploads them to GCS
3. Cloud Run downloads them to temp directory
4. `pipeline.py` passes absolute paths to image generation
5. Model generates images matching the reference style

### Tips

- Use 1-4 reference images per script
- Include brand colors, typography, visual style examples
- Reference images in prompts: "Use the same style as the given moodboard image..."
- Supported formats: PNG, JPG, WebP

## Validation

The script validates scripts before submission:

- Checks `reference_images` paths exist
- Validates required fields in script JSON
- Reports errors with specific file/line info

Use `--dry-run` to validate without submitting:

```bash
python batch/batch_cloudrun.py \
  --config batch/batch_config.json \
  --scripts-dir ./scripts \
  --output-dir ./output \
  --dry-run
```

## Troubleshooting

### Reference images not being used

Check `batch.json` in output - `reference_images` should have absolute paths like `/tmp/cloudrun_.../inputs/brand/filename.png`, not relative paths.

### Authentication errors

Ensure your service account key has:
- Cloud Run Invoker role
- Storage Object Admin role on the output bucket

### Job failures

Check Cloud Run logs:
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="explainer-mograph"' --limit=50
```

## Mock Mode (Testing)

Use `--mock` to run jobs with local test fixtures instead of calling the Replicate API. This is useful for testing the full Cloud Run pipeline flow without API costs.

```bash
# Run batch with mock mode
python batch/batch_cloudrun.py \
  --config batch/batch_config.json \
  --scripts-dir ./scripts \
  --mock

# Or set in config file
{
  "defaults": {
    "mock": true
  }
}
```

**What gets mocked on Cloud Run:**
- Image generation → uses `tests/fixtures/mock_image.png`
- Video generation → uses `tests/fixtures/mock_video.mp4`

**What still runs:**
- GCS uploads/downloads (real)
- Cloud Run HTTP calls (real)
- ElevenLabs TTS (real narration)
- FFmpeg assembly (real video processing)

This allows testing the full end-to-end flow (client → Cloud Run → GCS) in seconds instead of minutes per job.

## Local Development

Test server changes locally before deploying to Cloud Run.

### 1. Start the local server

```bash
# Set GCS credentials and start server on port 8080
GOOGLE_APPLICATION_CREDENTIALS="./your-service-account.json" python cloudrun/server.py
```

### 2. Run the client with `--local`

```bash
python batch/batch_cloudrun.py \
  --config batch/batch_config.json \
  --scripts-dir ./scripts \
  --output-dir ./local-output \
  --service-url http://localhost:8080 \
  --mock \
  --local
```

The `--local` flag skips Google identity token (not needed for localhost). The server still validates the API key.

**Benefits:**
- Faster iteration (no redeploy needed)
- ~12s per job locally vs ~42s via Cloud Run
- Full pipeline testing with real GCS and ElevenLabs

## Config Reference

### defaults

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `video_model` | string | `"fast"` | `"fast"` (Veo 3.1 Fast) or `"quality"` (Veo 3.1) |
| `video_seconds` | int | `6` | Video duration per scene (4, 6, or 8) |
| `start_frame_mode` | string | `"animate"` | How to pick first frame: `animate`, `transition`, `reference`, `sequential` |
| `stage` | string | `"final"` | Pipeline stage: `images`, `videos`, or `final` |
| `concurrency` | int | `5` | Max parallel Cloud Run jobs |
| `voice` | string | `"Rachel"` | ElevenLabs voice name |
| `enable_text_verification` | bool | `false` | Enable OpenAI vision verification |
| `mock` | bool | `false` | Use mock fixtures instead of Replicate API |
