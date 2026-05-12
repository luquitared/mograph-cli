# Cloud Run Deployment Guide

Deploy the Explainer MoGraph pipeline as a serverless HTTP API on Google Cloud Run.

> **For batch processing multiple videos**, use [`batch/batch_cloudrun.py`](../batch/README.md) which handles timeline uploads, reference images, and result downloads automatically.

## Overview

The Cloud Run deployment provides:
- **HTTP API**: RESTful endpoints for video generation
- **GCS Integration**: Inputs/outputs stored in Google Cloud Storage
- **Scalability**: Auto-scaling from 0 to N instances
- **Long-running Jobs**: Up to 60-minute request timeout

## Prerequisites

1. **Google Cloud Project** with billing enabled
2. **APIs Enabled**:
   - Cloud Run API
   - Cloud Build API
   - Secret Manager API
   - Cloud Storage API
3. **gcloud CLI** installed and authenticated
4. **API Keys** for:
   - OpenAI (`OPENAI_API_KEY`)
   - Replicate (`REPLICATE_API_TOKEN`)
   - ElevenLabs (`ELEVENLABS_API_KEY`)

## Quick Start

### 1. Set Up Secrets in Secret Manager

```bash
# Set your project
export PROJECT_ID=your-project-id
gcloud config set project $PROJECT_ID

# Create secrets
echo -n "sk-your-openai-key" | gcloud secrets create openai-api-key --data-file=-
echo -n "r8_your-replicate-token" | gcloud secrets create replicate-api-token --data-file=-
echo -n "your-elevenlabs-key" | gcloud secrets create elevenlabs-api-key --data-file=-
```

### 2. Create a GCS Bucket for Outputs

```bash
# For testing, use the pre-configured bucket:
export BUCKET_NAME=explainer-mograph-test-output

# Or create your own:
export BUCKET_NAME=explainer-mograph-outputs-$PROJECT_ID
gcloud storage buckets create gs://$BUCKET_NAME --location=us-central1

# Grant the service account access:
gcloud storage buckets add-iam-policy-binding gs://$BUCKET_NAME \
  --member="serviceAccount:snappy@eternal-skyline-475200-q6.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

### 3. Deploy with Cloud Build

```bash
gcloud builds submit --config cloudbuild.yaml .
```

### 4. Get the Service URL

```bash
gcloud run services describe explainer-mograph --region us-central1 --format='value(status.url)'
```

## Authentication

Cloud Run requires **IAM authentication** by default. You need to include an identity token in your requests.

### Getting an Identity Token

```bash
# Get identity token for the current user
gcloud auth print-identity-token

# Or for a service account
gcloud auth print-identity-token --impersonate-service-account=SA_EMAIL
```

### Making Authenticated Requests

```bash
SERVICE_URL=$(gcloud run services describe explainer-mograph --region us-central1 --format='value(status.url)')

# Include the Authorization header with Bearer token
curl -X POST "$SERVICE_URL/generate" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"timeline_file": "gs://bucket/inputs/timeline.json", "output_uri": "gs://bucket/output"}'
```

### From a SaaS Application

For server-to-server calls, use the Google Auth library with service account impersonation:

```javascript
const { GoogleAuth } = require('google-auth-library');

async function getIdentityToken(targetAudience) {
  const auth = new GoogleAuth();
  const client = await auth.getIdTokenClient(targetAudience);
  const token = await client.idTokenProvider.fetchIdToken(targetAudience);
  return token;
}

const idToken = await getIdentityToken(SERVICE_URL);
const response = await fetch(`${SERVICE_URL}/generate`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${idToken}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify(payload),
});
```

**Note:** The calling service account needs the `roles/run.invoker` role on the Cloud Run service.

## API Endpoints

### POST /generate

Run video generation synchronously (one job per Cloud Run instance).

**Request Body:**
```json
{
  "timeline_file": "gs://your-bucket/inputs/timeline.json",
  "output_uri": "gs://explainer-mograph-test-output/my-video",
  "stage": "final"
}
```

Or with inline timeline JSON:
```json
{
  "timeline_json": {
    "version": 1,
    "project": {"name": "my-explainer"},
    "tracks": [...]
  },
  "output_uri": "gs://explainer-mograph-test-output/my-video",
  "stage": "final"
}
```

**Response:**
```json
{
  "success": true,
  "job_id": "uuid-string",
  "output_uri": "gs://your-bucket/runs/my-video",
  "run_name": "my-explainer-20250126-143022",
  "files": [
    "gs://your-bucket/runs/my-video/final/final.mp4"
  ],
  "duration_seconds": 1234.5
}
```

### POST /generate/stream

Run video generation with **Server-Sent Events (SSE)** for real-time progress updates.

**Request Body:** Same as `/generate`

**Response:** SSE stream with progress events:

```
data: {"event": "job.started", "jobId": "abc123", "stage": "final", "timestamp": "..."}

data: {"event": "generation.completed", "jobId": "abc123", "videoUrl": "gs://...", "durationMs": 123456}
```

**Events:**
- `job.started` — Pipeline has started
- `asset.image` — An image was generated and uploaded (includes `assetUrl`)
- `asset.video` — A video was generated and uploaded (includes `assetUrl`)
- `asset.audio` — Audio was generated and uploaded (includes `assetUrl`)
- `asset.final` — Final video was generated and uploaded (includes `assetUrl`)
- `candidates.generated` — Exploration candidates are ready for selection (includes `manifest`)
- `selection.required` — Job is paused waiting for candidate selection (includes endpoint URLs)
- `generation.completed` — Full pipeline completed successfully
- `generation.failed` — Pipeline failed with error

**Asset Event Example:**
```json
{
  "event": "asset.image",
  "jobId": "abc123",
  "assetType": "image",
  "assetUrl": "gs://bucket/runs/my-video/images/scene01_hook.png",
  "fileName": "scene01_hook.png",
  "timestamp": "2025-01-26T14:30:22.123456"
}
```

**Exploration Pause Example:**
```json
{
  "event": "selection.required",
  "jobId": "abc123",
  "timestamp": "2025-01-26T14:30:22.123456",
  "phase": "images",
  "selectEndpoint": "/jobs/abc123/select",
  "candidatesEndpoint": "/jobs/abc123/candidates"
}
```

**JavaScript Example:**
```javascript
const response = await fetch(`${SERVICE_URL}/generate/stream`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${idToken}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify(payload),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const text = decoder.decode(value);
  const lines = text.split('\n');

  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const event = JSON.parse(line.slice(6));
      console.log('Progress:', event.event);

      if (event.event === 'generation.completed') {
        console.log('Video URL:', event.videoUrl);
      }

      if (event.event === 'selection.required') {
        // Handle exploration mode: fetch candidates and submit selections
        console.log('Selection needed for phase:', event.phase);
      }
    }
  }
}
```

### POST /validate

Validate a timeline document without executing it.

**Request Body:**
```json
{
  "timeline_json": {
    "version": 1,
    "project": {"name": "test"},
    "tracks": [...]
  }
}
```

**Response:**
```json
{
  "valid": true,
  "errors": [],
  "warnings": []
}
```

### GET /jobs/{job_id}/status

Check if a job is currently active (streaming).

**Response:**
```json
{
  "job_id": "abc123",
  "active": true,
  "timestamp": "2025-01-26T14:30:22.123456"
}
```

### POST /jobs/{job_id}/select

Submit candidate selections for exploration mode. When a timeline uses exploration (generating multiple candidates per node), the pipeline pauses and emits a `selection.required` SSE event. Use this endpoint to submit your selections and resume execution.

**Request Body:**
```json
{
  "phase": "images",
  "selections": {
    "node_id_1": [0],
    "node_id_2": [2]
  }
}
```

**Response:**
```json
{
  "status": "resumed",
  "phase": "images"
}
```

### GET /jobs/{job_id}/candidates

Get the current candidate manifest for a paused exploration job. Returns details about each node's candidates so you can make selections.

**Response:**
```json
{
  "job_id": "abc123",
  "phase": "images",
  "pending_selections": [
    {
      "id": "node_id_1",
      "type": "image",
      "media_type": "image/png",
      "select": 1,
      "candidates": [...]
    }
  ]
}
```

### GET /download/{job_id}/{file_path}

Download a single file from a job's output. Redirects (307) to a signed GCS URL.

```bash
curl -L "$SERVICE_URL/download/abc123/final/final.mp4" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -o final.mp4
```

### GET /download/{job_id}

List all files in a job's output with signed download URLs.

**Response:**
```json
{
  "job_id": "abc123",
  "files": [
    {"path": "images/scene01.png", "url": "https://storage.googleapis.com/..."},
    {"path": "final/final.mp4", "url": "https://storage.googleapis.com/..."}
  ]
}
```

### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-26T14:30:22.123456",
  "version": "2.0.0"
}
```

## Request Parameters

### Generate Request

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `timeline_json` | object | — | Inline timeline JSON (provide this or `timeline_file`) |
| `timeline_file` | string | — | GCS URI to timeline JSON file (provide this or `timeline_json`) |
| `output_uri` | string | — | GCS URI for output (gs://bucket/path) |
| `callback_url` | string | — | URL to POST status updates (webhook) |
| `callback_secret` | string | — | Secret for webhook authentication |
| `job_id` | string | auto | External job ID for tracking |
| `project_id` | string | — | External project ID |
| `stage` | string | "final" | Pipeline stage: `images`, `videos`, or `final` |
| `video_concurrency` | int | 8 | Concurrent video generation jobs |
| `mock` | bool | false | Use mock fixtures instead of API calls |

### Validate Request

| Parameter | Type | Description |
|-----------|------|-------------|
| `timeline_json` | object | Timeline JSON to validate (required) |

### Select Request

| Parameter | Type | Description |
|-----------|------|-------------|
| `phase` | string | Selection phase: `images`, `videos`, or `tts` (required) |
| `selections` | object | Mapping of node_id to list of selected candidate indices (required) |

> For full timeline format documentation, see [`docs/reference/timeline/`](../docs/reference/timeline/).

## Usage Examples

### Using curl

```bash
SERVICE_URL=$(gcloud run services describe explainer-mograph --region us-central1 --format='value(status.url)')

# Generate video from a GCS timeline file
curl -X POST "$SERVICE_URL/generate" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "timeline_file": "gs://explainer-mograph-test-output/inputs/timeline.json",
    "output_uri": "gs://explainer-mograph-test-output/runs/cloud-explainer",
    "stage": "final"
  }'

# Validate a timeline before running
curl -X POST "$SERVICE_URL/validate" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "timeline_json": {"version": 1, "project": {"name": "test"}, "tracks": []}
  }'

# List job files
curl "$SERVICE_URL/download/JOB_ID" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

### Using Python

```python
import requests

SERVICE_URL = "https://explainer-mograph-xxxxx-uc.a.run.app"

# Generate video from inline timeline
response = requests.post(f"{SERVICE_URL}/generate", json={
    "timeline_json": {
        "version": 1,
        "project": {"name": "ml-basics"},
        "tracks": [...]
    },
    "output_uri": "gs://explainer-mograph-test-output/runs/ml-basics",
})

result = response.json()
print(f"Output: {result['output_uri']}")
print(f"Final video: {result['files'][-1]}")
```

### Using gcloud

```bash
# Download the final video
gsutil cp gs://explainer-mograph-test-output/runs/my-video/final/final.mp4 ./

# List all outputs
gsutil ls -r gs://explainer-mograph-test-output/runs/my-video/
```

## Configuration Options

### Customize Deployment

Edit `cloudbuild.yaml` substitutions:

```yaml
substitutions:
  _SERVICE_NAME: explainer-mograph    # Service name
  _REGION: us-central1                # Deployment region
  _TIMEOUT: 3600s                     # Max request duration (60 min)
  _MEMORY: 4Gi                        # Memory allocation
  _CPU: "2"                           # CPU allocation
  _MAX_INSTANCES: "10"                # Max concurrent instances
  _MIN_INSTANCES: "0"                 # Min instances (0 = scale to zero)
```

### Manual Deployment

```bash
# Build image
docker build -t gcr.io/$PROJECT_ID/explainer-mograph -f cloudrun/Dockerfile .

# Push to Container Registry
docker push gcr.io/$PROJECT_ID/explainer-mograph

# Deploy to Cloud Run
gcloud run deploy explainer-mograph \
  --image gcr.io/$PROJECT_ID/explainer-mograph \
  --region us-central1 \
  --memory 4Gi \
  --cpu 2 \
  --timeout 3600s \
  --set-secrets 'OPENAI_API_KEY=openai-api-key:latest,REPLICATE_API_TOKEN=replicate-api-token:latest,ELEVENLABS_API_KEY=elevenlabs-api-key:latest'
```

## Cloud Run Jobs (Alternative)

For batch processing or very long jobs, consider using Cloud Run Jobs instead of the HTTP service:

```bash
# Create a job
gcloud run jobs create explainer-job \
  --image gcr.io/$PROJECT_ID/explainer-mograph \
  --region us-central1 \
  --memory 4Gi \
  --cpu 2 \
  --task-timeout 3600s \
  --set-secrets 'OPENAI_API_KEY=openai-api-key:latest,REPLICATE_API_TOKEN=replicate-api-token:latest,ELEVENLABS_API_KEY=elevenlabs-api-key:latest' \
  --set-env-vars 'PIPELINE_CONFIG={"timeline_file":"gs://bucket/inputs/timeline.json","output_uri":"gs://bucket/path"}'

# Execute the job
gcloud run jobs execute explainer-job --region us-central1 --wait
```

## Troubleshooting

### Common Issues

**1. Timeout Errors**
- Cloud Run has a max timeout of 60 minutes
- For longer jobs, use Cloud Run Jobs or break into stages
- Run just the `images` stage first, then `videos`, then `final`

**2. Memory Issues**
- Increase memory allocation: `--memory 8Gi`
- Process fewer scenes in parallel: reduce `video_concurrency`

**3. Authentication Errors**
- Verify secrets are correctly set in Secret Manager
- Check Cloud Run service account has `roles/secretmanager.secretAccessor`

**4. GCS Permission Errors**
- Grant the Cloud Run service account access to your bucket:
  ```bash
  SA_EMAIL=$(gcloud run services describe explainer-mograph --region us-central1 --format='value(spec.template.spec.serviceAccountName)')
  gsutil iam ch serviceAccount:$SA_EMAIL:objectAdmin gs://your-bucket
  ```

### View Logs

```bash
gcloud run services logs read explainer-mograph --region us-central1 --limit 100
```

## Cost Considerations

- **Cloud Run**: Pay per request duration and resources
- **Cloud Storage**: Pay for storage and network egress
- **External APIs**: OpenAI, Replicate, ElevenLabs have their own pricing

To minimize costs:
- Use `--stage images` to preview before generating videos
- Set `_MIN_INSTANCES: "0"` to scale to zero when idle
- Clean up old runs in GCS regularly

## Local Development

Test server changes locally before deploying to Cloud Run.

### Start the Server Locally

```bash
# Set GCS credentials and start server on port 8080
GOOGLE_APPLICATION_CREDENTIALS="./your-service-account.json" python cloudrun/server.py
```

### Test with curl

```bash
curl -X POST "http://localhost:8080/generate" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "timeline_json": {"version": 1, "project": {"name": "test"}, "tracks": []},
    "output_uri": "gs://explainer-mograph-test-output/test",
    "mock": true
  }'
```

### Test with batch client

```bash
python batch/batch_cloudrun.py \
  --config batch/batch_config.json \
  --timelines-dir ./timelines \
  --service-url http://localhost:8080 \
  --mock \
  --local
```

The `--local` flag skips Google identity token (not needed for localhost).
