# cloudrun/

Cloud Run HTTP API deployment — FastAPI server for remote video generation with GCS integration, webhook callbacks, and SSE streaming.

## Files

- `server.py` — FastAPI app with `/generate`, `/generate/stream`, `/health`, `/validate`, `/jobs/{id}/status`, `/jobs/{id}/select`, `/jobs/{id}/candidates`, and `/download` endpoints. Runs timeline pipeline in a thread pool, watches output directory for new assets, uploads them to GCS incrementally, and emits progress events via webhooks/SSE.
- `gcs_storage.py` — GCS upload/download/signed URL helpers and `GCSWorkspace` class that manages a temp local workspace with GCS sync. Handles input download and output upload.
- `CLOUDRUN.md` — Comprehensive API documentation (prerequisites, deployment steps, endpoint reference, config)
- `Dockerfile` — Container image for Cloud Run
- `cloudbuild.yaml` — Cloud Build config used by `scripts/deploy.sh`
- `requirements.txt` — Python dependencies for the container

## Key Interfaces

- **Endpoints**: `POST /generate` (sync), `POST /generate/stream` (SSE), `POST /validate`, `GET /health`, `GET /jobs/{job_id}/status`, `POST /jobs/{job_id}/select`, `GET /jobs/{job_id}/candidates`, `GET /download/{job_id}/{file_path:path}`, `GET /download/{job_id}`
- **Input**: Timeline format only (`timeline_json` or `timeline_file`)
- **Auth**: Bearer token or `X-API-Key` header checked against `PIPELINE_API_KEY` env var
- **Asset watcher**: Background thread scans run directory for new images/videos/audio, uploads to GCS, emits SSE events
- **Exploration**: Candidate selection via `/jobs/{id}/select` endpoint for exploration mode timelines

## Dependencies

- **Imports from**: `timeline/` package, `cloudrun/gcs_storage.py`, `google.cloud.storage`
- **Imported by**: nothing (deployed as standalone service)
- **Deployment**: `scripts/deploy.sh` → `gcloud builds submit --config cloudrun/cloudbuild.yaml`

> See `CLOUDRUN.md` for full API documentation.
