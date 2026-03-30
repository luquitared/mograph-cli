# batch/

Batch processing client for Cloud Run — submits multiple video generation jobs in parallel, handles reference image uploads, and downloads results from GCS.

## Files

- `batch_cloudrun.py` — Async CLI client that reads script JSON files from a directory, uploads reference images to GCS, submits jobs to `/generate` endpoint concurrently via `aiohttp`, and downloads results. Supports per-script `pipeline_config` overrides.
- `batch_config.example.json` — Config template with service URL, output bucket, and pipeline defaults
- `README.md` — Setup and usage documentation
- `test-scripts/` — Test fixture scripts for batch testing

## Key Interfaces

- **CLI**: `python batch/batch_cloudrun.py --config batch_config.json --scripts-dir ./scripts`
- **Config layering**: JSON config file → CLI args → per-script `pipeline_config` in each script JSON
- **Auth**: Uses Google Cloud identity token for IAM + API key for app-level auth
- **Script discovery**: Finds `*.json` files with a `scenes` key in the scripts directory

## Dependencies

- **Imports from**: `aiohttp`, `google.cloud.storage`, `google.auth` (no local pipeline imports)
- **Imported by**: nothing (standalone CLI tool)
