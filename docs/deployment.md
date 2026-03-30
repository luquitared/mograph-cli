# Deployment

The pipeline runs on **Google Cloud Run** as a FastAPI server, deployed via **Cloud Build**.

## Architecture

```
Webapp (Next.js on Vercel) --> Cloud Run (FastAPI) --> GCS (inputs/outputs)
                                    |
                         Replicate, Gemini TTS, OpenAI
```

- **Service**: `explainer-mograph` in `us-central1`
- **URL**: `https://explainer-mograph-oga4i5mv6a-uc.a.run.app`
- **Resources**: 8GB RAM, 2 CPU, 0-10 instances, 60min timeout, 1 request/container
- **Secrets**: Via Google Secret Manager (openai, replicate, elevenlabs, google API keys)

## Deploying

```bash
# Production
./scripts/deploy.sh

# Staging
./scripts/deploy.sh --staging
```

This writes a `VERSION` file with the git commit SHA and timestamp, then runs `gcloud builds submit --config cloudbuild.yaml .`

### Version Tracking

After deploying, `/health` returns the deployed commit:

```bash
curl -s https://explainer-mograph-oga4i5mv6a-uc.a.run.app/health | jq
# {"status":"healthy","version":"2.0.0","commit":"fe2f5eb...","branch":"main","deployed_at":"2026-03-14T03:25:04Z"}
```

### Manual Deploy

```bash
gcloud builds submit --config cloudbuild.yaml .
```

## Authentication

The API uses two auth layers:

1. **API Key** (always required): Set `PIPELINE_API_KEY` env var or defaults to `explainer-mograph-secret-key-2024`
   - Pass via `Authorization: Bearer <key>` or `X-API-Key: <key>` header
2. **Cloud Run IAM** (currently disabled): `--allow-unauthenticated` is set in `cloudbuild.yaml`

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check + version info |
| `/generate` | POST | Synchronous video generation |
| `/generate/stream` | POST | SSE streaming with real-time progress |
| `/jobs/{job_id}/status` | GET | Check if a job is active |
| `/download/{job_id}/{file_path}` | GET | Single file signed URL redirect |
| `/download/{job_id}` | GET | List all files with signed URLs |

See [cloudrun/CLOUDRUN.md](../cloudrun/CLOUDRUN.md) for full API reference with request/response schemas.

## API Keys Required

| Mode           | Required Keys                                                 |
| -------------- | ------------------------------------------------------------- |
| Script mode    | `REPLICATE_API_TOKEN`, `GOOGLE_API_KEY`                       |
| TTS-only mode  | `GOOGLE_API_KEY`                                              |
| Voice mode     | `DEEPGRAM_API_KEY`, `REPLICATE_API_TOKEN`, `GOOGLE_API_KEY`   |

## Local Development

```bash
# Start server locally
GOOGLE_APPLICATION_CREDENTIALS="./your-sa-key.json" python cloudrun/server.py

# Test with curl
curl -X POST "http://localhost:8080/generate" \
  -H "X-API-Key: explainer-mograph-secret-key-2024" \
  -H "Content-Type: application/json" \
  -d '{"script_json": {...}, "mock": true}'
```

## GCS Output

Outputs go to `gs://eternal-skyline-475200-q6-explainer-outputs/`. Each run gets a directory with images, videos, audio, and final assembled videos.

```bash
# List runs
gsutil ls gs://eternal-skyline-475200-q6-explainer-outputs/

# Download a final video
gsutil cp gs://.../<run-id>/final/final.mp4 ./
```

## Batch Processing

For running multiple scripts in parallel via Cloud Run, see [batch/README.md](../batch/README.md).

## Customizing the Deploy

Edit `cloudbuild.yaml` substitutions:

```yaml
substitutions:
  _SERVICE_NAME: explainer-mograph
  _REGION: us-central1
  _TIMEOUT: 3600s    # 60 min max request
  _MEMORY: 8Gi
  _CPU: "2"
  _MAX_INSTANCES: "10"
  _MIN_INSTANCES: "0"  # Scale to zero
```
