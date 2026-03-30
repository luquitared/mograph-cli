# Deployment Guide

## Quick Deploy

```bash
# 1. Build the Docker image
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/eternal-skyline-475200-q6/cloud-run-source-deploy/explainer-mograph:latest \
  --project eternal-skyline-475200-q6 \
  --timeout 1800

# 2. Deploy to Cloud Run
gcloud run deploy explainer-mograph \
  --image us-central1-docker.pkg.dev/eternal-skyline-475200-q6/cloud-run-source-deploy/explainer-mograph:latest \
  --region us-central1 \
  --project eternal-skyline-475200-q6
```

## Full Deploy with All Options

```bash
gcloud run deploy explainer-mograph \
  --image us-central1-docker.pkg.dev/eternal-skyline-475200-q6/cloud-run-source-deploy/explainer-mograph:latest \
  --region us-central1 \
  --memory 16Gi \
  --cpu 4 \
  --timeout 3600 \
  --no-cpu-throttling \
  --service-account video-pipeline-invoker@eternal-skyline-475200-q6.iam.gserviceaccount.com \
  --project eternal-skyline-475200-q6 \
  --set-env-vars "GCS_OUTPUT_BUCKET=gs://eternal-skyline-475200-q6-explainer-outputs" \
  --allow-unauthenticated
```

## Service Accounts

| Environment | Service Account |
|-------------|-----------------|
| Cloud Run (prod) | `video-pipeline-invoker@eternal-skyline-475200-q6.iam.gserviceaccount.com` |
| Local | `snappy@eternal-skyline-475200-q6.iam.gserviceaccount.com` |

## GCS Bucket

- **Bucket**: `gs://eternal-skyline-475200-q6-explainer-outputs`
- **Public access**: Enabled (allUsers:objectViewer)
- **Output URLs**: `https://storage.googleapis.com/eternal-skyline-475200-q6-explainer-outputs/...`

## Check Logs

```bash
# Recent logs
gcloud run services logs read explainer-mograph --region us-central1 --project eternal-skyline-475200-q6 --limit 100

# Search for specific patterns
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="explainer-mograph"' \
  --project eternal-skyline-475200-q6 \
  --limit 50 \
  --format="value(timestamp,textPayload)" \
  --freshness=30m
```

## Check Service Status

```bash
# List services
gcloud run services list --region us-central1 --project eternal-skyline-475200-q6

# Describe service
gcloud run services describe explainer-mograph --region us-central1 --project eternal-skyline-475200-q6

# Check env vars
gcloud run services describe explainer-mograph --region us-central1 --project eternal-skyline-475200-q6 \
  --format="yaml(spec.template.spec.containers[0].env)"
```
