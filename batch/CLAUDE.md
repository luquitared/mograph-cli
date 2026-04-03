# batch/

Batch processing client for Cloud Run — submits multiple video generation jobs from timeline JSON files in parallel and downloads results from GCS.

## Files

- `batch_cloudrun.py` — Async CLI client that reads timeline JSON files from a directory, submits jobs to `/generate` endpoint concurrently via `aiohttp`, and downloads results.
- `batch_config.example.json` — Config template with service URL, output bucket, and defaults (stage, concurrency, mock)
- `README.md` — Setup and usage documentation
- `test-scripts/` — Test fixture timelines for batch testing

## Key Interfaces

- **CLI**: `python batch/batch_cloudrun.py --config batch_config.json --timelines-dir ./timelines`
- **Config layering**: JSON config file → CLI args
- **Auth**: Uses Google Cloud identity token for IAM + API key for app-level auth
- **Timeline discovery**: Finds `*.json` files with `project` and `tracks` keys (timeline format)

## Dependencies

- **Imports from**: `aiohttp`, `google.cloud.storage`, `google.auth` (no local pipeline imports)
- **Imported by**: nothing (standalone CLI tool)
