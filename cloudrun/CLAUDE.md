# cloudrun/

Cloud Run HTTP API deployment — FastAPI server for remote video generation with GCS integration, webhook callbacks, and SSE streaming.

## Files

- `server.py` — FastAPI app with `/generate`, `/generate/stream`, `/health`, `/jobs/{id}/status`, and `/download` endpoints. Runs pipeline in a thread pool, watches output directory for new assets, uploads them to GCS incrementally, and emits progress events via webhooks/SSE.
- `gcs_storage.py` — GCS upload/download/signed URL helpers and `GCSWorkspace` class that manages a temp local workspace with GCS sync. Handles input download and output upload.
- `CLOUDRUN.md` — Comprehensive API documentation (prerequisites, deployment steps, endpoint reference, config)
- `Dockerfile` — Container image for Cloud Run
- `cloudbuild.yaml` — Cloud Build config used by `scripts/deploy.sh`
- `requirements.txt` — Python dependencies for the container

## Key Interfaces

- **Pipeline import**: `pipeline.py` is loaded once at module level via `importlib` (lines 40-44), not re-imported per request
- **Endpoints**: `POST /generate` (sync), `POST /generate/stream` (SSE), `GET /health`, `GET /jobs/{job_id}/status`, `GET /download/{job_id}/{file_path:path}` (single file signed URL redirect), `GET /download/{job_id}` (list all files with signed URLs)
- **Auth**: Bearer token or `X-API-Key` header checked against `PIPELINE_API_KEY` env var
- **Asset watcher**: Background thread scans run directory for new images/videos/audio, uploads to GCS, deletes local copy to prevent tmpfs exhaustion, emits SSE events
- **Thread safety**: Relies on `shared/replicate_client.py` thread-local state for concurrent requests

## Dependencies

- **Imports from**: `pipeline.py` (via importlib), `cloudrun/gcs_storage.py`, `google.cloud.storage`
- **Imported by**: nothing (deployed as standalone service)
- **Deployment**: `scripts/deploy.sh` → `gcloud builds submit --config cloudrun/cloudbuild.yaml`

> See `CLOUDRUN.md` for full API documentation.
