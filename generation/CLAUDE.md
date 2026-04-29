# generation/

Image and video generation backends. Images support Nano Banana Pro (Replicate), Nano Banana 2 (Gemini API direct), and GPT Image 2 (Replicate). Videos use Seedance 2.0 Fast (default) or Seedance 2.0 via Replicate.

## Files

- `batch_img.py` — Batch image generation via Replicate's `google/nano-banana-pro`, with async concurrency, upload/poll/download, and optional OpenAI vision quality verification with auto-regeneration
- `nano_banana2.py` — Burst-mode image generation via Gemini API direct (`gemini-3.1-flash-image-preview`)
- `gpt_image2.py` — Single-image generation via Replicate's `openai/gpt-image-2`
- `batch_vid.py` — Batch video generation via Replicate (Seedance 2.0 / Seedance 2.0 Fast), with content moderation retry and rate limit handling

## Key Interfaces

**batch_img.py:**
- `run_batch(batch_path, ...)` — Sync wrapper used by pipeline.py. Takes a batch JSON path, returns list of image Paths
- `run_batch_streaming(json_path, on_image_complete=callback, ...)` — Streaming variant that fires a callback as each image completes (enables stage overlap)
- `run_batch_async(json_path, ...)` — Core async implementation
- `MOCK_REPLICATE` — Module-level bool set by pipeline.py when `--mock` is active

**gpt_image2.py:**
- `generate_image(session, prompt, output_path, ...)` — Single-image generation with reference images, aspect ratio, quality/background/compression controls
- `MOCK_REPLICATE` — Mock mode control set by pipeline.py

**nano_banana2.py:**
- `generate_image(session, prompt, output_path, ...)` — Burst-mode Gemini generation
- `MOCK_GENERATE` — Mock mode control set by pipeline.py

**batch_vid.py:**
- `run_batch_async(jobs_path, outdir, model_kind="seedance-fast", ...)` — Async batch video generation. `model_kind` selects "seedance-fast" (default) or "seedance"
- `process_job(...)` — Single job processor for Seedance
- `MOCK_REPLICATE` / `MOCK_VIDEO_FIXTURE` — Mock mode controls set by pipeline.py

**Input formats:**
- Images: JSON with `requests[]` array (each has `prompt`, `image_paths`, `filename`, `output_dir`)
- Videos: JSON array of jobs (each has `prompt`, optional `first_frame_image`/`last_frame_image`, `reference_images`, `reference_videos`, `reference_audios`, `config`)

## Dependencies

- **Imports from**: `shared.common` (ensure_dir, sanitize_filename, guess_mime_image), `shared.replicate_client` (upload, predict, poll, download)
- **Imported by**: `pipeline.py`
