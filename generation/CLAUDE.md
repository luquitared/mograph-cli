# generation/

Image and video generation via Replicate API. Images use Google Nano Banana Pro; videos use Google Veo 3.1 (quality/fast).

## Files

- `batch_img.py` — Batch image generation with async concurrency, Replicate upload/poll/download, and optional OpenAI vision quality verification with auto-regeneration
- `batch_vid.py` — Batch video generation supporting Veo 3.1 (quality/fast) models, with content moderation retry and rate limit handling

## Key Interfaces

**batch_img.py:**
- `run_batch(batch_path, ...)` — Sync wrapper used by pipeline.py. Takes a batch JSON path, returns list of image Paths
- `run_batch_streaming(json_path, on_image_complete=callback, ...)` — Streaming variant that fires a callback as each image completes (enables stage overlap)
- `run_batch_async(json_path, ...)` — Core async implementation
- `MOCK_REPLICATE` — Module-level bool set by pipeline.py when `--mock` is active

**batch_vid.py:**
- `run_batch_async(jobs_path, outdir, model_kind="quality", ...)` — Async batch video generation. `model_kind` selects "quality" (Veo 3.1) or "fast" (Veo 3.1 Fast)
- `process_job(...)` — Single job processor for Veo
- `MOCK_REPLICATE` / `MOCK_VIDEO_FIXTURE` — Mock mode controls set by pipeline.py

**Input formats:**
- Images: JSON with `requests[]` array (each has `prompt`, `image_paths`, `filename`, `output_dir`)
- Videos: JSON array of jobs (each has `prompt`, optional `first_frame_image`/`last_frame_image`, `config`)

## Dependencies

- **Imports from**: `shared.common` (ensure_dir, sanitize_filename, guess_mime_image), `shared.replicate_client` (upload, predict, poll, download)
- **Imported by**: `pipeline.py`
