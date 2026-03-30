#!/usr/bin/env python3
"""FastAPI server for running the explainer-mograph pipeline on Cloud Run.

Provides HTTP endpoints for:
- /generate: Run video generation (synchronous)
- /generate/stream: Run video generation with SSE progress streaming
- /health: Health check endpoint

Supports both webhook callbacks and SSE for real-time progress updates.
Uploads assets incrementally and emits GCS URLs as they're generated.
"""

import argparse
import asyncio
import json
import os
import queue
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from cloudrun import gcs_storage
from cloudrun.gcs_storage import GCSWorkspace

# Import pipeline.py module once at startup (not the pipeline/ package)
import importlib.util as _importlib_util
_pipeline_path = Path(__file__).parent.parent / "pipeline.py"
_pipeline_spec = _importlib_util.spec_from_file_location("pipeline_module", str(_pipeline_path))
_pipeline_module = _importlib_util.module_from_spec(_pipeline_spec)
_pipeline_spec.loader.exec_module(_pipeline_module)

# Thread pool for running pipeline (avoids asyncio.run() conflicts)
executor = ThreadPoolExecutor(max_workers=4)

# Active SSE connections for progress streaming
active_streams: Dict[str, queue.Queue] = {}

# Active file watchers
active_watchers: Dict[str, bool] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    _load_env()
    yield
    executor.shutdown(wait=False)


app = FastAPI(
    title="Explainer MoGraph Pipeline",
    description="AI-powered motion graphics explainer video generation",
    version="2.0.0",
    lifespan=lifespan,
)

# Simple API key authentication
API_KEY = os.environ.get("PIPELINE_API_KEY")
if not API_KEY:
    import warnings
    warnings.warn("PIPELINE_API_KEY not set — API authentication will reject all requests")


def verify_api_key(request: Request) -> bool:
    """Verify the API key from request headers."""
    if not API_KEY:
        return False
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == API_KEY:
            return True
    api_key = request.headers.get("X-API-Key", "")
    if api_key == API_KEY:
        return True
    return False


class VideoModel(str, Enum):
    """Available video generation models."""
    QUALITY = "quality"
    FAST = "fast"
    KLING = "kling"


class StartFrameMode(str, Enum):
    """How to pick the starting frame for each video."""
    TRANSITION = "transition"
    REFERENCE = "reference"
    SEQUENTIAL = "sequential"
    ANIMATE = "animate"


class TimingMode(str, Enum):
    """How to reconcile audio/video length mismatches."""
    AUDIO_MATCH = "audio-match"
    VIDEO_MATCH = "video-match"


class PipelineStage(str, Enum):
    """Pipeline stages."""
    IMAGES = "images"
    VIDEOS = "videos"
    FINAL = "final"


class GenerateRequest(BaseModel):
    """Request body for video generation."""
    # Input options (one required)
    script_file: Optional[str] = Field(None, description="GCS URI to existing script.json")
    script_json: Optional[dict] = Field(None, description="Inline script JSON (alternative to script_file)")
    voice_file: Optional[str] = Field(None, description="GCS URI to voice recording (mp3, wav, m4a)")

    # Reference images
    reference_images: List[str] = Field(default_factory=list, description="GCS URIs to style reference images")
    main_ref: Optional[str] = Field(None, description="GCS URI to aspect ratio reference image")

    # Output
    output_uri: Optional[str] = Field(None, description="GCS URI for output (gs://bucket/path). Optional for local testing.")

    # Callback options
    callback_url: Optional[str] = Field(None, description="URL to POST status updates (webhook)")
    callback_secret: Optional[str] = Field(None, description="Secret for webhook authentication")
    job_id: Optional[str] = Field(None, description="External job ID for tracking")
    project_id: Optional[str] = Field(None, description="External project ID")

    # Pipeline control
    stage: PipelineStage = Field(PipelineStage.FINAL, description="Pipeline stage: images, videos, or final")

    # Video generation options
    video_model: VideoModel = Field(VideoModel.FAST, description="Video model: quality, fast, or kling")
    video_seconds: int = Field(6, description="Video duration per scene (4, 6, or 8)")
    video_resolution: str = Field("720p", description="Video resolution")
    video_concurrency: int = Field(8, description="Concurrent video generation jobs")
    video_buffer_ms: int = Field(0, description="Add/subtract ms from video duration")
    timing_mode: TimingMode = Field(TimingMode.AUDIO_MATCH, description="Audio/video sync: audio-match or video-match")
    start_frame_mode: StartFrameMode = Field(StartFrameMode.ANIMATE, description="How to pick first frame")

    # Audio/TTS options (Gemini TTS)
    voice: str = Field("Kore", description="Gemini TTS voice name (e.g., Kore, Puck, Charon)")
    tts_model: str = Field("gemini-2.5-flash-preview-tts", description="Gemini TTS model")
    tts_concurrency: int = Field(5, description="Concurrent TTS requests")
    veo_audio_volume: float = Field(0.3, description="Veo SFX volume in combined version (0.0-1.0)")

    # Mode options
    tts_only: bool = Field(False, description="TTS-only mode: generate TTS + timestamps, then stop")
    images_only: bool = Field(False, description="Images-only mode: skip video generation, produce slideshow with narration")
    target_seconds: int = Field(30, description="Target video duration for narration generation (default: 30)")

    # Image generation options
    image_model: str = Field("google/nano-banana-pro", description="Image generation model")
    concurrency: int = Field(6, description="Concurrent image generation jobs")
    max_images: Optional[int] = Field(None, description="Maximum images to generate")
    disable_text_verification: bool = Field(True, description="Skip image quality verification")
    alternatives: bool = Field(False, description="Generate alternative visuals")

    # Testing
    mock: bool = Field(False, description="Use mock fixtures instead of API calls")


class ProgressEvent(BaseModel):
    """Progress event for SSE streaming."""
    event: str
    job_id: str
    project_id: Optional[str] = None
    stage: Optional[str] = None
    progress: Optional[float] = None
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class GenerateResponse(BaseModel):
    """Response for synchronous generation."""
    success: bool
    job_id: str
    output_uri: str
    run_name: str
    files: List[str]
    duration_seconds: float


def _resolve_timing_mode(request: "GenerateRequest") -> str:
    """Return the timing mode value for the pipeline."""
    return request.timing_mode.value


def _load_env():
    """Load environment variables from .env file if present."""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _send_webhook(callback_url: Optional[str], payload: dict, callback_secret: Optional[str] = None, max_retries: int = 3):
    """Send webhook notification with retry logic."""
    if not callback_url:
        return

    # Block SSRF to internal services
    import ipaddress as _ipaddress
    from urllib.parse import urlparse
    parsed = urlparse(callback_url)
    hostname = parsed.hostname or ""
    blocked_hosts = {"metadata.google.internal", "localhost"}
    if hostname in blocked_hosts:
        print(f"[SERVER] Blocked webhook to internal address: {hostname}", flush=True)
        return
    try:
        addr = _ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            print(f"[SERVER] Blocked webhook to private/reserved IP: {hostname}", flush=True)
            return
    except ValueError:
        # hostname is a DNS name, not an IP — resolve and check
        import socket
        try:
            resolved = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in resolved:
                addr = _ipaddress.ip_address(sockaddr[0])
                if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                    print(f"[SERVER] Blocked webhook to private/reserved IP: {hostname} -> {sockaddr[0]}", flush=True)
                    return
        except socket.gaierror:
            pass  # DNS resolution failed — allow attempt, will fail at request time

    import requests
    import time

    print(f"[WEBHOOK] Sending {payload.get('event')} to {callback_url}")

    headers = {"Content-Type": "application/json"}
    if callback_secret:
        headers["X-Callback-Secret"] = callback_secret

    for attempt in range(max_retries):
        try:
            response = requests.post(callback_url, json=payload, headers=headers, timeout=30)
            if response.status_code < 500:
                if response.status_code >= 400:
                    print(f"[WEBHOOK] Client error: {response.status_code} - {response.text[:200]}")
                return
        except requests.exceptions.ConnectionError as e:
            print(f"[WEBHOOK] Connection failed (attempt {attempt + 1}/{max_retries}): {e}")
        except requests.exceptions.Timeout:
            print(f"[WEBHOOK] Timeout (attempt {attempt + 1}/{max_retries})")
        except Exception as e:
            print(f"[WEBHOOK] Error: {type(e).__name__}: {e}")

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    print(f"[WEBHOOK] Failed after {max_retries} attempts")


def _emit_progress(
    job_id: str,
    event: str,
    callback_url: Optional[str] = None,
    callback_secret: Optional[str] = None,
    project_id: Optional[str] = None,
    **kwargs
):
    """Emit a progress event to both webhook and SSE stream."""
    payload = {
        "event": event,
        "jobId": job_id,
        "projectId": project_id,
        "timestamp": datetime.utcnow().isoformat(),
        **kwargs
    }

    print(f"[EMIT] Event: {event}, job_id: {job_id}, callback_url: {callback_url}, SSE active: {job_id in active_streams}", flush=True)

    # Send to webhook
    if callback_url:
        _send_webhook(callback_url, payload, callback_secret=callback_secret)

    # Send to SSE stream if active
    if job_id in active_streams:
        try:
            active_streams[job_id].put_nowait(payload)
        except queue.Full:
            pass  # Drop event if queue is full


def _build_pipeline_args(request: GenerateRequest, inputs: dict, workspace: GCSWorkspace) -> argparse.Namespace:
    """Build argparse.Namespace from request for pipeline.main()."""
    # Determine main_ref path
    if inputs.get("main_ref"):
        main_ref_path = str(inputs["main_ref"])
    else:
        default_ref = Path(__file__).parent.parent / "assets/images/main-ref-images/blank_white_9x16.png"
        main_ref_path = str(default_ref) if default_ref.exists() else "assets/images/main-ref-images/blank_white_9x16.png"

    return argparse.Namespace(
        # Input
        script_file=str(inputs["script_file"]) if inputs.get("script_file") else None,
        voice_file=str(inputs["voice_file"]) if inputs.get("voice_file") else None,

        # References
        reference_images=[str(p) for p in inputs.get("reference_images", [])],
        main_ref=main_ref_path,

        # Pipeline control
        stage=request.stage.value,
        resume_dir=None,
        output_root=str(workspace.runs_dir),
        dry_run=False,
        mock=request.mock,

        # Video options
        video_model=request.video_model.value,
        video_seconds=request.video_seconds,
        video_resolution=request.video_resolution,
        video_concurrency=request.video_concurrency,
        video_poll_sec=2.5,
        video_buffer_ms=request.video_buffer_ms,
        # Timing mode (pipeline uses timing_mode and sets video_length_mode for backwards compat)
        timing_mode=_resolve_timing_mode(request),
        video_length_mode=_resolve_timing_mode(request),
        start_frame_mode=request.start_frame_mode.value,

        # Audio/TTS options
        voice=request.voice,
        tts_model=request.tts_model,
        tts_concurrency=request.tts_concurrency,
        veo_audio_volume=request.veo_audio_volume,

        # Mode options
        tts_only=request.tts_only,
        target_seconds=request.target_seconds,

        # Image options
        image_model=request.image_model,
        concurrency=request.concurrency,
        max_images=request.max_images,
        disable_text_verification=request.disable_text_verification,
        alternatives=request.alternatives,

        # Output
        final_name="final.mp4",

        # Test/special modes
        images_only=request.images_only,

        # Flags not exposed in API
        list_voices=False,
    )


def _run_pipeline_sync(request: GenerateRequest, job_id: str) -> dict:
    """Execute the pipeline synchronously with progress reporting.

    Starts a background asset watcher that uploads images/videos to GCS
    as they're generated, emitting SSE events with URLs for each asset.
    """
    pipeline_module = _pipeline_module

    # Determine output destination:
    # 1. Use request.output_uri if provided
    # 2. Fall back to GCS_OUTPUT_BUCKET env var
    # 3. Fall back to LOCAL_OUTPUT_DIR for local-only mode
    output_uri = request.output_uri
    if not output_uri:
        output_uri = os.environ.get("GCS_OUTPUT_BUCKET")

    local_output_dir = os.environ.get("LOCAL_OUTPUT_DIR")
    if local_output_dir and not output_uri:
        workspace = GCSWorkspace(None, local_base=Path(local_output_dir))
    else:
        workspace = GCSWorkspace(output_uri)
    external_job_id = request.job_id or job_id
    project_id = request.project_id
    callback_url = request.callback_url
    callback_secret = request.callback_secret
    watcher_thread = None
    run_dir = None

    try:
        # Handle inline script_json
        if request.script_json and not request.script_file:
            script_temp = workspace.inputs_dir / "script.json"
            script_temp.write_text(json.dumps(request.script_json, indent=2))
            script_file_gcs = None
            inline_script_path = str(script_temp)
        else:
            script_file_gcs = request.script_file
            inline_script_path = None

        # Download inputs from GCS
        inputs = workspace.download_inputs(
            reference_images=request.reference_images,
            main_ref=request.main_ref,
            script_file=script_file_gcs,
            voice_file=request.voice_file,
        )

        # Use inline script if provided
        if inline_script_path:
            inputs["script_file"] = Path(inline_script_path)

        # Build pipeline args
        args = _build_pipeline_args(request, inputs, workspace)

        # Emit: job started
        _emit_progress(
            external_job_id, "job.started",
            callback_url=callback_url,
            callback_secret=callback_secret,
            project_id=project_id,
            stage=request.stage.value,
        )

        # Start asset watcher on parent runs_dir - it will detect when run directory is created
        def watch_runs_directory():
            """Watch for new run directories and then watch their contents."""
            seen_files: Set[Path] = set()
            detected_run_dir: Optional[Path] = None

            # GCS setup (only if not local-only mode)
            bucket = None
            bucket_name = None
            prefix = ""
            if not workspace.is_local_only:
                from google.cloud import storage
                gcs_base = workspace.output_uri
                if gcs_base.startswith("gs://"):
                    gcs_base = gcs_base[5:]
                bucket_name, *prefix_parts = gcs_base.split("/", 1)
                prefix = prefix_parts[0] if prefix_parts else ""

                try:
                    client = storage.Client()
                    bucket = client.bucket(bucket_name)
                except Exception as e:
                    print(f"[WATCHER] Failed to init GCS client: {e}")
                    return

            def upload_and_emit(file_path: Path, asset_type: str, current_run_dir: Path):
                """Upload a single file (if GCS enabled) and emit progress event."""
                if file_path in seen_files:
                    return

                # Wait for file to be stable (not being written)
                # Finals need extra checks — ffmpeg writes data then seeks back to write moov atom
                is_mp4 = file_path.suffix.lower() == ".mp4"
                checks = 3 if (is_mp4 and asset_type == "final") else 2
                wait_per_check = 3 if (is_mp4 and asset_type == "final") else 2 if is_mp4 else 1
                try:
                    prev_size = file_path.stat().st_size
                    if prev_size == 0:
                        return
                    for _ in range(checks):
                        time.sleep(wait_per_check)
                        curr_size = file_path.stat().st_size
                        if curr_size != prev_size or curr_size == 0:
                            print(f"[WATCHER] File still being written, skipping for now: {file_path.name}")
                            return  # Will be picked up on next scan
                        prev_size = curr_size
                except Exception:
                    return  # File might have been deleted

                seen_files.add(file_path)

                try:
                    if workspace.is_local_only:
                        # Local-only mode: just emit event with local path
                        asset_url = f"file://{file_path}"
                        print(f"[WATCHER] Local asset {asset_type}: {file_path.name}")
                    else:
                        # GCS mode: upload and emit GCS URL
                        rel_path = file_path.relative_to(current_run_dir)
                        gcs_path = f"{prefix}/{current_run_dir.name}/{rel_path}" if prefix else f"{current_run_dir.name}/{rel_path}"

                        bucket.blob(gcs_path).upload_from_filename(str(file_path))
                        asset_url = f"gs://{bucket_name}/{gcs_path}"
                        print(f"[WATCHER] Uploaded {asset_type}: {file_path.name}")

                        # Note: we intentionally do NOT delete local files here.
                        # The watcher runs concurrently with the pipeline, and deleting files
                        # causes race conditions (images needed for video generation, scene videos
                        # needed for final concat, final mp4 needed for ffmpeg moov atom faststart).
                        # Cleanup happens in the finally block via workspace.cleanup().

                    _emit_progress(
                        external_job_id,
                        f"asset.{asset_type}",
                        callback_url=callback_url,
                        callback_secret=callback_secret,
                        project_id=project_id,
                        assetType=asset_type,
                        assetUrl=asset_url,
                        fileName=file_path.name,
                    )
                except Exception as e:
                    print(f"[WATCHER] Failed to process {file_path.name}: {e}")

            def scan_directory(directory: Path, asset_type: str, extensions: tuple, current_run_dir: Path):
                if not directory.exists():
                    return
                for file_path in directory.iterdir():
                    if file_path.is_file() and file_path.suffix.lower() in extensions:
                        upload_and_emit(file_path, asset_type, current_run_dir)

            print(f"[WATCHER] Starting - watching {workspace.runs_dir}")
            active_watchers[external_job_id] = True

            while active_watchers.get(external_job_id, False):
                try:
                    # Find the most recent run directory
                    if workspace.runs_dir.exists():
                        run_dirs = sorted(
                            [d for d in workspace.runs_dir.iterdir() if d.is_dir()],
                            key=lambda p: p.stat().st_mtime,
                            reverse=True
                        )
                        if run_dirs:
                            detected_run_dir = run_dirs[0]

                    if detected_run_dir:
                        # Scan for assets
                        scan_directory(detected_run_dir / "images", "image", (".png", ".jpg", ".jpeg", ".webp"), detected_run_dir)
                        scan_directory(detected_run_dir / "videos", "video", (".mp4", ".webm"), detected_run_dir)
                        scan_directory(detected_run_dir / "audio", "audio", (".mp3", ".wav", ".m4a"), detected_run_dir)
                        scan_directory(detected_run_dir / "final", "final", (".mp4",), detected_run_dir)

                except Exception as e:
                    print(f"[WATCHER] Error: {e}")

                time.sleep(2)

            print(f"[WATCHER] Stopped")

        # Start watcher thread
        watcher_thread = threading.Thread(target=watch_runs_directory, daemon=True)
        watcher_thread.start()

        # Run pipeline
        start_time = datetime.utcnow()
        print(f"=== STARTING PIPELINE ===", flush=True)
        print(f"Job ID: {external_job_id}", flush=True)
        print(f"Stage: {request.stage.value}", flush=True)
        print(f"Mock mode: {request.mock}", flush=True)

        try:
            run_dir = pipeline_module.main(args)
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            print(f"=== PIPELINE COMPLETED in {duration:.1f}s ===", flush=True)

        except Exception as e:
            end_time = datetime.utcnow()
            error_msg = str(e)
            print(f"=== PIPELINE FAILED: {error_msg} ===", flush=True)
            print(traceback.format_exc(), flush=True)

            _emit_progress(
                external_job_id, "generation.failed",
                callback_url=callback_url,
                callback_secret=callback_secret,
                project_id=project_id,
                error=error_msg,
            )

            tb = traceback.format_exc()
            print(f"[SERVER] Pipeline error traceback:\n{tb}", flush=True)
            return {
                "success": False,
                "job_id": job_id,
                "error": error_msg,
            }

        # Give watcher time to upload final files
        print("[SERVER] Waiting 3s for watcher to finish uploads...", flush=True)
        time.sleep(3)

        # Stop the watcher
        print("[SERVER] Stopping watcher...", flush=True)
        active_watchers[external_job_id] = False
        if watcher_thread:
            watcher_thread.join(timeout=5)

        # Find the run directory if not returned
        print(f"[SERVER] Finding run directory (run_dir={run_dir})...", flush=True)
        if not run_dir or not Path(run_dir).exists():
            run_dirs = sorted(workspace.runs_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not run_dirs:
                return {"success": False, "job_id": job_id, "error": "No run directory created"}
            run_dir = run_dirs[0]
        else:
            run_dir = Path(run_dir)
        print(f"[SERVER] Run directory: {run_dir}", flush=True)

        # Upload any remaining outputs to GCS (ensures everything is uploaded)
        # Use external_job_id (from frontend's postgres ID) to create unique GCS paths
        print(f"[SERVER] Uploading remaining outputs to GCS (job_id={external_job_id})...", flush=True)
        upload_result = workspace.upload_outputs(run_dir, job_id=external_job_id)
        print(f"[SERVER] Upload complete: {len(upload_result.get('files', []))} files", flush=True)

        # Find final video URL (prefer signed URLs for browser access)
        final_video_url = None
        thumbnail_url = None
        signed_urls = upload_result.get("signed_urls", upload_result["files"])
        gcs_files = upload_result["files"]

        # Zip gcs_uris with signed_urls to find matching pairs
        for gcs_uri, signed_url in zip(gcs_files, signed_urls):
            if "final_with_sfx.mp4" in gcs_uri:
                final_video_url = signed_url
            elif "final.mp4" in gcs_uri and not final_video_url:
                final_video_url = signed_url
            if gcs_uri.endswith((".jpg", ".png")) and not thumbnail_url:
                thumbnail_url = signed_url
        print(f"[SERVER] Final video URL: {final_video_url}", flush=True)

        # Emit: generation completed
        print(f"[SERVER] Emitting generation.completed event (callback_url={callback_url})...", flush=True)
        if request.tts_only:
            _emit_progress(
                external_job_id, "generation.completed",
                callback_url=callback_url,
                callback_secret=callback_secret,
                project_id=project_id,
                ttsOnly=True,
                durationMs=int(duration * 1000),
                runDirectory=upload_result["gcs_base"],
                files=upload_result["files"],
            )
        else:
            _emit_progress(
                external_job_id, "generation.completed",
                callback_url=callback_url,
                callback_secret=callback_secret,
                project_id=project_id,
                videoUrl=final_video_url,
                thumbnailUrl=thumbnail_url,
                durationMs=int(duration * 1000),
                runDirectory=upload_result["gcs_base"],
                files=upload_result["files"],
            )
        print("[SERVER] generation.completed event emitted", flush=True)

        return {
            "success": True,
            "job_id": job_id,
            "output_uri": upload_result["gcs_base"],
            "run_name": upload_result["run_name"],
            "files": upload_result["files"],
            "signed_urls": upload_result.get("signed_urls", []),
            "video_url": final_video_url,
            "duration_seconds": duration,
        }

    except Exception as e:
        _emit_progress(
            external_job_id, "generation.failed",
            callback_url=callback_url,
            callback_secret=callback_secret,
            project_id=project_id,
            error=str(e),
        )
        tb = traceback.format_exc()
        print(f"[SERVER] Pipeline error traceback:\n{tb}", flush=True)
        return {
            "success": False,
            "job_id": job_id,
            "error": str(e),
        }

    finally:
        # Stop watcher if running
        if external_job_id in active_watchers:
            active_watchers[external_job_id] = False
            del active_watchers[external_job_id]

        workspace.cleanup()

        # Clean up SSE stream if active
        if external_job_id in active_streams:
            active_streams[external_job_id].put(None)  # Signal end
            del active_streams[external_job_id]


_version_info = None


def _load_version() -> dict:
    """Load version info from VERSION file."""
    global _version_info
    if _version_info is None:
        version_path = Path(__file__).parent.parent / "VERSION"
        if version_path.exists():
            try:
                _version_info = json.loads(version_path.read_text())
            except Exception:
                _version_info = {}
        else:
            _version_info = {}
    return _version_info


@app.get("/health")
async def health():
    """Health check endpoint."""
    version_info = _load_version()
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0",
        **version_info,
    }


@app.post("/generate", response_model=None)
async def generate(request: GenerateRequest, raw_request: Request):
    """Run video generation synchronously (one job per Cloud Run instance)."""
    if not verify_api_key(raw_request):
        raise HTTPException(401, "Invalid or missing API key")

    if not request.script_file and not request.script_json and not request.voice_file:
        raise HTTPException(400, "One of 'script_file', 'script_json', or 'voice_file' is required")

    job_id = str(uuid.uuid4())

    # Run in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, _run_pipeline_sync, request, job_id)

    if result["success"]:
        return GenerateResponse(**result)
    else:
        raise HTTPException(500, detail=result)


@app.post("/generate/stream")
async def generate_stream(request: GenerateRequest, raw_request: Request):
    """Run video generation with SSE streaming for real-time progress updates.

    Returns a Server-Sent Events stream with progress updates.
    Events: job.started, stage.started, stage.completed, generation.completed, generation.failed
    """
    if not verify_api_key(raw_request):
        raise HTTPException(401, "Invalid or missing API key")

    if not request.script_file and not request.script_json and not request.voice_file:
        raise HTTPException(400, "One of 'script_file', 'script_json', or 'voice_file' is required")

    job_id = request.job_id or str(uuid.uuid4())

    # Prevent overwriting an active stream
    if job_id in active_streams:
        raise HTTPException(409, f"Job ID '{job_id}' is already active")

    # Create SSE queue for this job
    event_queue: queue.Queue = queue.Queue(maxsize=100)
    active_streams[job_id] = event_queue

    # Start pipeline in background thread
    def run_in_background():
        _run_pipeline_sync(request, job_id)

    executor.submit(run_in_background)

    async def event_generator():
        """Generate SSE events from queue."""
        try:
            while True:
                try:
                    # Non-blocking check with timeout
                    event = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: event_queue.get(timeout=1.0)
                    )

                    if event is None:  # End signal
                        break

                    yield f"data: {json.dumps(event)}\n\n"

                    # Check for terminal events
                    if event.get("event") in ("generation.completed", "generation.failed"):
                        break

                except queue.Empty:
                    # Send keepalive
                    yield f": keepalive\n\n"

        finally:
            # Cleanup
            if job_id in active_streams:
                del active_streams[job_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Job-ID": job_id,
        }
    )


@app.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str, raw_request: Request):
    """Check if a job is currently streaming."""
    if not verify_api_key(raw_request):
        raise HTTPException(401, "Invalid or missing API key")

    is_active = job_id in active_streams
    return {
        "job_id": job_id,
        "active": is_active,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/download/{job_id}/{file_path:path}")
async def download_file(job_id: str, file_path: str, raw_request: Request):
    """Download a single file from a job's output via signed URL."""
    if not verify_api_key(raw_request):
        raise HTTPException(401, "Invalid or missing API key")

    # Prevent path traversal
    if ".." in file_path or file_path.startswith("/"):
        raise HTTPException(400, "Invalid file path")

    bucket = os.environ.get("GCS_OUTPUT_BUCKET")
    if not bucket:
        raise HTTPException(500, "GCS_OUTPUT_BUCKET environment variable not set")

    gcs_uri = f"gs://{bucket}/{job_id}/{file_path}"

    # Check if the blob exists
    try:
        bucket_name, blob_path = gcs_storage.parse_gcs_uri(gcs_uri)
        client = gcs_storage.get_gcs_client()
        blob = client.bucket(bucket_name).blob(blob_path)
        if not blob.exists():
            raise HTTPException(404, f"File not found: {job_id}/{file_path}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error checking file existence: {e}")

    try:
        signed_url = gcs_storage.generate_signed_url(gcs_uri)
    except Exception as e:
        raise HTTPException(500, f"Error generating signed URL: {e}")

    return RedirectResponse(url=signed_url, status_code=307)


@app.get("/download/{job_id}")
async def download_job_files(job_id: str, raw_request: Request):
    """List all files in a job's output with signed URLs."""
    if not verify_api_key(raw_request):
        raise HTTPException(401, "Invalid or missing API key")

    bucket = os.environ.get("GCS_OUTPUT_BUCKET")
    if not bucket:
        raise HTTPException(500, "GCS_OUTPUT_BUCKET environment variable not set")

    gcs_prefix = f"gs://{bucket}/{job_id}/"

    try:
        file_uris = gcs_storage.list_files(gcs_prefix)
    except Exception as e:
        raise HTTPException(500, f"Error listing files: {e}")

    if not file_uris:
        raise HTTPException(404, f"No files found for job: {job_id}")

    files = []
    for uri in file_uris:
        _, blob_path = gcs_storage.parse_gcs_uri(uri)
        # Get path relative to job_id prefix
        relative_path = blob_path[len(f"{job_id}/"):]
        if not relative_path:
            continue
        try:
            signed_url = gcs_storage.generate_signed_url(uri)
        except Exception as e:
            raise HTTPException(500, f"Error generating signed URL for {relative_path}: {e}")
        files.append({"path": relative_path, "url": signed_url})

    if not files:
        raise HTTPException(404, f"No files found for job: {job_id}")

    return {"job_id": job_id, "files": files}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
