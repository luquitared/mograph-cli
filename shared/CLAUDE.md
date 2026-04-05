# shared/

Common utilities shared across the codebase: FFmpeg media processing, Replicate API client, and small helpers.

## Files

- `media.py` — FFmpeg wrappers for video/audio operations: `probe_duration`, `trim_video`, `extend_video`, `change_video_speed`, `overlay_audio`, `overlay_combined_audio`, `concat_videos`, `concat_audio`, `change_audio_speed`, `extract_last_frame`, `image_to_video`, `extract_audio_segment`, `generate_silence`, `detect_aspect_ratio`. Each has an `_async` variant for parallel Stage 3 processing.
- `replicate_client.py` — Replicate API client with async upload (cached), predict, poll, and download. Thread-safe state via `threading.local()` for `mock_mode`, `tts_test_mode`, and `upload_cache`.
- `common.py` — Small helpers: `ensure_dir`, `guess_mime_image`, `sanitize_filename`, `slugify_identifier`, `encode_image_as_data_url`
- `r2_storage.py` — Async Cloudflare R2 upload via S3 API with aiohttp + SigV4 signing. Used by models needing public URLs (Seedance). Dedup-cached, thread-safe, no new deps.
- `env_loader.py` — Shared `.env` file loader: `load_env_file`

## Key Interfaces

**replicate_client.py:**
- `upload_file_to_replicate(session, file_path)` — Upload with dedup cache
- `start_prediction(session, owner, name, inputs)` — Start a Replicate prediction
- `poll_prediction(session, pred)` — Poll until completion
- `download_to(session, url, dest)` — Download result (handles `file://` for mock)
- `set_mock_mode(enabled)` / `is_mock_mode()` — Per-thread mock control
- `is_content_moderation_error(e)` / `is_rate_limit_error(e)` — Error classifiers

**Thread safety:** `replicate_client.py` uses `threading.local()` so each Cloud Run request thread gets its own `mock_mode`, `tts_test_mode`, and `upload_cache`. The async upload lock is per-event-loop.

**media.py:**
- Sync functions for pipeline.py's sequential processing
- Async variants (`*_async`) for concurrent Stage 3 video assembly

## Dependencies

- **Imports from**: `aiohttp`, `PIL` (media.py only)
- **Imported by**: `pipeline.py`, `cloudrun/server.py`, `generation/`, `tts/`, `pipeline/`, and most other modules
