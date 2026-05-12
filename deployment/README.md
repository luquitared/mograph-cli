# Deployment

The pipeline runs on **Google Cloud Run** as a FastAPI server, deployed via **Cloud Build**.

## Architecture

```
Webapp (Next.js on Vercel) --> Cloud Run (FastAPI) --> GCS (inputs/outputs)
                                    |
                              Replicate, Gemini TTS
```

- **Service**: `explainer-mograph` in `us-central1`
- **Project**: `eternal-skyline-475200-q6`
- **Resources**: 8GB RAM, 2 CPU, 0-10 instances, 60min timeout, 1 request/container
- **Secrets**: Via Google Secret Manager

## Deploy

```bash
# Production
./deployment/deploy.sh

# Staging (limited to 3 instances)
./deployment/deploy.sh --env staging
```

The script writes a `VERSION` file with git commit + timestamp, then runs `gcloud builds submit --config cloudrun/cloudbuild.yaml`.

After deploying, verify with:

```bash
curl -s https://explainer-mograph-oga4i5mv6a-uc.a.run.app/health | jq
```

### Manual deploy

```bash
# Build
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/eternal-skyline-475200-q6/cloud-run-source-deploy/explainer-mograph:latest \
  --project eternal-skyline-475200-q6 \
  --timeout 1800

# Deploy
gcloud run deploy explainer-mograph \
  --image us-central1-docker.pkg.dev/eternal-skyline-475200-q6/cloud-run-source-deploy/explainer-mograph:latest \
  --region us-central1 \
  --project eternal-skyline-475200-q6 \
  --memory 8Gi --cpu 2 --timeout 3600 --no-cpu-throttling \
  --service-account video-pipeline-invoker@eternal-skyline-475200-q6.iam.gserviceaccount.com \
  --set-env-vars "GCS_OUTPUT_BUCKET=gs://eternal-skyline-475200-q6-explainer-outputs" \
  --allow-unauthenticated
```

## Authentication

- **API Key** (required): `Authorization: Bearer <key>` or `X-API-Key: <key>` header
- **Cloud Run IAM**: Currently disabled (`--allow-unauthenticated`)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check + version info |
| `/generate` | POST | Synchronous video generation |
| `/generate/stream` | POST | SSE streaming with real-time progress |
| `/jobs/{job_id}/status` | GET | Check if a job is active |
| `/download/{job_id}/{file_path}` | GET | Single file signed URL redirect |
| `/download/{job_id}` | GET | List all files with signed URLs |

See [cloudrun/CLOUDRUN.md](../cloudrun/CLOUDRUN.md) for full API reference.

## API Keys Required

| Mode | Required Keys |
|------|---------------|
| Script mode | `REPLICATE_API_TOKEN`, `GOOGLE_API_KEY` |
| TTS-only | `GOOGLE_API_KEY` |

## Service Accounts

| Environment | Service Account |
|-------------|-----------------|
| Cloud Run | `video-pipeline-invoker@eternal-skyline-475200-q6.iam.gserviceaccount.com` |
| Local | `snappy@eternal-skyline-475200-q6.iam.gserviceaccount.com` |

## GCS Output

- **Bucket**: `gs://eternal-skyline-475200-q6-explainer-outputs`
- **Public URL**: `https://storage.googleapis.com/eternal-skyline-475200-q6-explainer-outputs/...`

```bash
gsutil ls gs://eternal-skyline-475200-q6-explainer-outputs/
```

## Logs

```bash
gcloud run services logs read explainer-mograph --region us-central1 --project eternal-skyline-475200-q6 --limit 100
```

## Local Development

```bash
GOOGLE_APPLICATION_CREDENTIALS="./your-sa-key.json" python cloudrun/server.py

curl -X POST "http://localhost:8080/generate" \
  -H "X-API-Key: explainer-mograph-secret-key-2024" \
  -H "Content-Type: application/json" \
  -d '{"script_json": {...}, "mock": true}'
```
