# Batch Cloud Run Client

Run multiple video generation jobs on Cloud Run in parallel. This client handles submitting timeline JSON files to Cloud Run and downloading results from GCS.

## Quick Start

```bash
# From the project root
python batch/batch_cloudrun.py \
  --config batch/batch_config.json \
  --timelines-dir ./timelines \
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
    "stage": "final",
    "concurrency": 5,
    "mock": false
  }
}
```

| Field | Description |
|-------|-------------|
| `service_url` | Your Cloud Run service URL |
| `output_bucket` | GCS bucket for outputs (without `gs://` prefix) |
| `service_account_key` | Path to service account JSON key file |
| `defaults` | Default pipeline settings |

### 2. Prepare Timelines

Create a folder with your timeline JSON files:

```
timelines/
  video1.json
  video2.json
  video3.json
```

Each file should be a valid timeline with `project` and `tracks` keys. All generation parameters (video model, voice, etc.) are embedded in the timeline itself.

## Usage

### Basic Usage

```bash
python batch/batch_cloudrun.py \
  --config batch/batch_config.json \
  --timelines-dir ./timelines \
  --output-dir ./output
```

### All Options

```bash
python batch/batch_cloudrun.py \
  --config CONFIG_FILE             # Path to batch_config.json
  --timelines-dir TIMELINES_DIR    # Directory containing timeline JSON files
  --output-dir OUTPUT_DIR          # Directory to download results to
  --concurrency N                  # Max parallel jobs (default: from config)
  --stage STAGE                    # Pipeline stage: images, videos, or final
  --dry-run                        # Validate without running
  --validate-only                  # Only validate timeline files
  --skip-download                  # Skip downloading results from GCS
  --mock                           # Use mock fixtures for testing
  --local                          # Run against local server
```

## Output Structure

After running, results are downloaded to your output directory:

```
output/
  video1/
    images/
      *.png                # Generated images
    videos/
      *.mp4                # Generated video clips
    audio/
      *.mp3                # Generated narration
    final/
      final.mp4            # Final assembled video
  video2/
    ...
  batch_metrics.json       # Overall batch metrics
```

## Validation

The client validates timeline files before submission:

- Checks JSON is valid
- Validates required `tracks` field exists

Use `--dry-run` to validate without submitting:

```bash
python batch/batch_cloudrun.py \
  --config batch/batch_config.json \
  --timelines-dir ./timelines \
  --dry-run
```

## Troubleshooting

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

Use `--mock` to run jobs with test fixtures instead of real API calls. This is useful for testing the full Cloud Run pipeline flow without API costs.

```bash
python batch/batch_cloudrun.py \
  --config batch/batch_config.json \
  --timelines-dir ./timelines \
  --mock
```

**What gets mocked on Cloud Run:**
- Image generation → uses `tests/fixtures/mock_image.png`
- Video generation → uses `tests/fixtures/mock_video.mp4`

**What still runs:**
- GCS uploads/downloads (real)
- Cloud Run HTTP calls (real)
- TTS generation (real narration)
- FFmpeg assembly (real video processing)

## Local Development

Test server changes locally before deploying to Cloud Run.

### 1. Start the local server

```bash
GOOGLE_APPLICATION_CREDENTIALS="./your-service-account.json" python cloudrun/server.py
```

### 2. Run the client with `--local`

```bash
python batch/batch_cloudrun.py \
  --config batch/batch_config.json \
  --timelines-dir ./timelines \
  --output-dir ./local-output \
  --service-url http://localhost:8080 \
  --mock \
  --local
```

The `--local` flag skips Google identity token (not needed for localhost). The server still validates the API key.

## Config Reference

### defaults

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `stage` | string | `"final"` | Pipeline stage: `images`, `videos`, or `final` |
| `concurrency` | int | `5` | Max parallel Cloud Run jobs |
| `mock` | bool | `false` | Use mock fixtures instead of real API calls |
