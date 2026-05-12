#!/usr/bin/env python3
"""FastAPI server for running the explainer-mograph pipeline on Cloud Run.

Provides HTTP endpoints for:
- /generate: Run video generation (synchronous)
- /generate/stream: Run video generation with SSE progress streaming
- /health: Health check endpoint

Supports both webhook callbacks and SSE for real-time progress updates.
Uploads assets incrementally and emits r2:// URIs as they're generated.
"""

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

from cloudrun import r2_storage
from cloudrun.r2_storage import R2Workspace


def _default_output_uri() -> Optional[str]:
    """Resolve the default object-storage prefix for pipeline outputs.

    Preference order: explicit R2_OUTPUT_URI, then R2_BUCKET_NAME (synthesized
    as r2://<bucket>/cloudrun-outputs), then the legacy GCS_OUTPUT_BUCKET (still
    usable because r2_storage.parse_uri accepts gs:// for back-compat).
    """
    explicit = os.environ.get("R2_OUTPUT_URI")
    if explicit:
        return explicit
    bucket = os.environ.get("R2_BUCKET_NAME") or os.environ.get("R2_BUCKET")
    if bucket:
        return f"r2://{bucket.strip().strip('/')}/cloudrun-outputs"
    return os.environ.get("GCS_OUTPUT_BUCKET")

# Thread pool for running pipeline (avoids asyncio.run() conflicts)
executor = ThreadPoolExecutor(max_workers=4)

# Active SSE connections for progress streaming
active_streams: Dict[str, queue.Queue] = {}

# Active file watchers
active_watchers: Dict[str, bool] = {}

# Exploration state for timeline jobs (per-job candidate selection)
_exploration_lock = threading.Lock()  # Guards access to the dicts below
_exploration_states: Dict[str, "ExplorationState"] = {}
_job_run_dirs: Dict[str, Path] = {}


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


class PipelineStage(str, Enum):
    """Pipeline stages."""
    IMAGES = "images"
    VIDEOS = "videos"
    FINAL = "final"


class GenerateRequest(BaseModel):
    """Request body for timeline-based video generation."""
    # Timeline input (one required)
    timeline_json: Optional[dict] = Field(None, description="Inline timeline JSON")
    timeline_file: Optional[str] = Field(None, description="R2 URI to timeline JSON file (r2:// or gs://)")

    # Output
    output_uri: Optional[str] = Field(None, description="R2 URI for output (r2://bucket/path; gs:// also accepted). Optional for local testing.")

    # Callback options
    callback_url: Optional[str] = Field(None, description="URL to POST status updates (webhook)")
    callback_secret: Optional[str] = Field(None, description="Secret for webhook authentication")
    job_id: Optional[str] = Field(None, description="External job ID for tracking")
    project_id: Optional[str] = Field(None, description="External project ID")

    # Pipeline control
    stage: PipelineStage = Field(PipelineStage.FINAL, description="Pipeline stage: images, videos, or final")
    video_concurrency: int = Field(8, description="Concurrent video generation jobs")

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

    # SSRF prevention — validate URL before making request
    from timeline.security import SecurityError, validate_url
    try:
        validate_url(callback_url)
    except SecurityError as e:
        print(f"[SERVER] Blocked webhook to disallowed URL: {e}", flush=True)
        return

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


def _run_timeline_sync(request: GenerateRequest, job_id: str) -> dict:
    """Execute the timeline pipeline synchronously with progress reporting.

    Uses R2Workspace, asset watcher, and SSE event patterns for real-time updates.
    """
    from timeline.parser import parse_timeline
    from timeline.validator import validate as validate_timeline_doc
    from timeline.executor import execute_timeline
    from timeline.run_context import create_run_dir
    from timeline.explorer import ExplorationState, read_manifest, validate_selections, write_selections

    # Determine output destination
    output_uri = request.output_uri
    if not output_uri:
        output_uri = _default_output_uri()

    local_output_dir = os.environ.get("LOCAL_OUTPUT_DIR")
    if local_output_dir and not output_uri:
        workspace = R2Workspace(None, local_base=Path(local_output_dir))
    else:
        workspace = R2Workspace(output_uri)

    external_job_id = request.job_id or job_id
    project_id = request.project_id
    callback_url = request.callback_url
    callback_secret = request.callback_secret
    watcher_thread = None
    run_dir = None
    timeline_dir = None

    try:
        # Parse the timeline
        if request.timeline_json:
            timeline = parse_timeline(request.timeline_json)
            timeline_dir = workspace.local_base
        elif request.timeline_file:
            # Download from R2
            inputs = workspace.download_inputs(
                timeline_file=request.timeline_file,
                reference_images=[],
            )
            local_path = inputs.get("timeline_file")
            if not local_path:
                return {"success": False, "job_id": job_id, "error": "Failed to download timeline file"}
            timeline = parse_timeline(local_path)
            timeline_dir = Path(local_path).parent
        else:
            return {"success": False, "job_id": job_id, "error": "No timeline input provided"}

        # Validate
        val_result = validate_timeline_doc(timeline, timeline_dir=timeline_dir)
        if not val_result.is_valid:
            return {
                "success": False,
                "job_id": job_id,
                "errors": [{"path": e.path, "message": e.message} for e in val_result.errors],
            }

        # Create run directory
        run_dir = create_run_dir(timeline.project.name, base_dir=workspace.runs_dir)

        # Set up exploration state for candidate selection
        exploration_state = ExplorationState()
        with _exploration_lock:
            _exploration_states[external_job_id] = exploration_state
            _job_run_dirs[external_job_id] = run_dir

        # Emit: job started
        _emit_progress(
            external_job_id, "job.started",
            callback_url=callback_url,
            callback_secret=callback_secret,
            project_id=project_id,
            stage=request.stage.value,
        )

        # Start asset watcher
        def watch_runs_directory():
            """Watch for new assets in the run directory."""
            seen_files: Set[Path] = set()

            bucket_name = None
            prefix = ""
            r2_client = None
            if not workspace.is_local_only:
                bucket_name, prefix = r2_storage.parse_uri(workspace.output_uri)
                try:
                    r2_client = r2_storage.get_client()
                except Exception as e:
                    print(f"[WATCHER-TL] Failed to init R2 client: {e}")
                    return

            def upload_and_emit(file_path: Path, asset_type: str):
                if file_path in seen_files:
                    return
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
                            return
                        prev_size = curr_size
                except Exception:
                    return
                seen_files.add(file_path)
                try:
                    if workspace.is_local_only:
                        asset_url = f"file://{file_path}"
                    else:
                        rel_path = file_path.relative_to(run_dir)
                        r2_key = (
                            f"{prefix}/{run_dir.name}/{rel_path}"
                            if prefix
                            else f"{run_dir.name}/{rel_path}"
                        )
                        r2_client.upload_file(str(file_path), bucket_name, r2_key)
                        asset_url = f"r2://{bucket_name}/{r2_key}"
                    _emit_progress(
                        external_job_id, f"asset.{asset_type}",
                        callback_url=callback_url,
                        callback_secret=callback_secret,
                        project_id=project_id,
                        assetType=asset_type,
                        assetUrl=asset_url,
                        fileName=file_path.name,
                    )
                except Exception as e:
                    print(f"[WATCHER-TL] Failed to process {file_path.name}: {e}")

            def scan_directory(directory: Path, asset_type: str, extensions: tuple):
                if not directory.exists():
                    return
                for file_path in directory.iterdir():
                    if file_path.is_file() and file_path.suffix.lower() in extensions:
                        upload_and_emit(file_path, asset_type)

            print(f"[WATCHER-TL] Starting - watching {run_dir}")
            active_watchers[external_job_id] = True

            while active_watchers.get(external_job_id, False):
                try:
                    scan_directory(run_dir / "images", "image", (".png", ".jpg", ".jpeg", ".webp"))
                    scan_directory(run_dir / "videos", "video", (".mp4", ".webm"))
                    scan_directory(run_dir / "audio", "audio", (".mp3", ".wav", ".m4a"))
                    scan_directory(run_dir / "final", "final", (".mp4",))
                except Exception as e:
                    print(f"[WATCHER-TL] Error: {e}")
                time.sleep(2)

            print(f"[WATCHER-TL] Stopped")

        watcher_thread = threading.Thread(target=watch_runs_directory, daemon=True)
        watcher_thread.start()

        # Execute timeline
        start_time = datetime.utcnow()
        print(f"=== STARTING TIMELINE PIPELINE ===", flush=True)
        print(f"Job ID: {external_job_id}", flush=True)
        print(f"Project: {timeline.project.name}", flush=True)
        print(f"Stage: {request.stage.value}", flush=True)
        print(f"Mock mode: {request.mock}", flush=True)

        try:
            run_result = execute_timeline(
                timeline=timeline,
                run_dir=run_dir,
                stage=request.stage.value,
                mock=request.mock,
                concurrency={"video": request.video_concurrency},
                timeline_dir=timeline_dir,
                exploration_state=exploration_state,
            )
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            print(f"=== TIMELINE PIPELINE COMPLETED in {duration:.1f}s ===", flush=True)

        except Exception as e:
            end_time = datetime.utcnow()
            error_msg = str(e)
            print(f"=== TIMELINE PIPELINE FAILED: {error_msg} ===", flush=True)
            print(traceback.format_exc(), flush=True)

            _emit_progress(
                external_job_id, "generation.failed",
                callback_url=callback_url,
                callback_secret=callback_secret,
                project_id=project_id,
                error=error_msg,
            )
            return {"success": False, "job_id": job_id, "error": error_msg}

        # Give watcher time to upload final files
        print("[SERVER-TL] Waiting 3s for watcher to finish uploads...", flush=True)
        time.sleep(3)

        # Stop the watcher
        active_watchers[external_job_id] = False
        if watcher_thread:
            watcher_thread.join(timeout=5)

        if not run_result.success:
            _emit_progress(
                external_job_id, "generation.failed",
                callback_url=callback_url,
                callback_secret=callback_secret,
                project_id=project_id,
                error="; ".join(run_result.errors),
            )
            return {
                "success": False,
                "job_id": job_id,
                "error": "; ".join(run_result.errors),
            }

        # Upload remaining outputs to R2
        print(f"[SERVER-TL] Uploading outputs to R2 (job_id={external_job_id})...", flush=True)
        upload_result = workspace.upload_outputs(run_dir, job_id=external_job_id)
        print(f"[SERVER-TL] Upload complete: {len(upload_result.get('files', []))} files", flush=True)

        # Find final video URL
        final_video_url = None
        thumbnail_url = None
        signed_urls = upload_result.get("signed_urls", upload_result["files"])
        uploaded_files = upload_result["files"]

        for object_uri, signed_url in zip(uploaded_files, signed_urls):
            if "final_with_sfx.mp4" in object_uri:
                final_video_url = signed_url
            elif "final.mp4" in object_uri and not final_video_url:
                final_video_url = signed_url
            if object_uri.endswith((".jpg", ".png")) and not thumbnail_url:
                thumbnail_url = signed_url

        # Emit: generation completed
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
        print(f"[SERVER-TL] Pipeline error traceback:\n{tb}", flush=True)
        return {"success": False, "job_id": job_id, "error": str(e)}

    finally:
        if external_job_id in active_watchers:
            active_watchers[external_job_id] = False
            del active_watchers[external_job_id]

        # Mark exploration as completed before cleanup (prevents race with in-flight requests)
        with _exploration_lock:
            state = _exploration_states.get(external_job_id)
            if state:
                state.mark_completed()

        # Clean up exploration state
        with _exploration_lock:
            _exploration_states.pop(external_job_id, None)
            _job_run_dirs.pop(external_job_id, None)

        workspace.cleanup()

        if external_job_id in active_streams:
            active_streams[external_job_id].put(None)
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

    if not any([request.timeline_json, request.timeline_file]):
        raise HTTPException(400, "One of 'timeline_json' or 'timeline_file' is required")

    if request.timeline_json:
        size = len(json.dumps(request.timeline_json))
        if size > 1_048_576:  # 1MB
            raise HTTPException(413, "Timeline JSON exceeds 1MB size limit")

    job_id = str(uuid.uuid4())

    # Run in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, _run_timeline_sync, request, job_id)

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

    if not any([request.timeline_json, request.timeline_file]):
        raise HTTPException(400, "One of 'timeline_json' or 'timeline_file' is required")

    if request.timeline_json:
        size = len(json.dumps(request.timeline_json))
        if size > 1_048_576:  # 1MB
            raise HTTPException(413, "Timeline JSON exceeds 1MB size limit")

    job_id = request.job_id or str(uuid.uuid4())

    # Prevent overwriting an active stream
    if job_id in active_streams:
        raise HTTPException(409, f"Job ID '{job_id}' is already active")

    # Create SSE queue for this job
    event_queue: queue.Queue = queue.Queue(maxsize=100)
    active_streams[job_id] = event_queue

    # Start pipeline in background thread
    def run_in_background():
        _run_timeline_sync(request, job_id)

    executor.submit(run_in_background)

    async def event_generator():
        """Generate SSE events from queue, including exploration pause events."""
        already_emitted_pause: Optional[str] = None  # Track which phase pause we've emitted
        try:
            while True:
                try:
                    # Non-blocking check with timeout
                    event = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: event_queue.get(timeout=0.5)
                    )

                    if event is None:  # End signal
                        break

                    yield f"data: {json.dumps(event)}\n\n"

                    # Check for terminal events
                    if event.get("event") in ("generation.completed", "generation.failed"):
                        break

                except queue.Empty:
                    pass  # Fall through to exploration check below

                # Check if exploration is paused
                with _exploration_lock:
                    state = _exploration_states.get(job_id)
                    run_dir = _job_run_dirs.get(job_id)

                paused = False
                if state and run_dir:
                    paused, phase = state.get_pause_state()
                    if paused and phase and phase != already_emitted_pause:
                        already_emitted_pause = phase
                        # Read manifest from disk
                        from timeline.explorer import read_manifest as _read_manifest
                        manifest = _read_manifest(run_dir, phase)
                        manifest_summary = {}
                        if manifest:
                            manifest_summary = {
                                "phase": manifest.phase,
                                "pending_count": len(manifest.pending_selections),
                                "items": [
                                    {
                                        "id": ps.id,
                                        "type": ps.type,
                                        "media_type": ps.media_type,
                                        "select": ps.select,
                                        "candidate_count": len(ps.candidates),
                                    }
                                    for ps in manifest.pending_selections
                                ],
                            }

                        # Emit candidates.generated event
                        candidates_event = {
                            "event": "candidates.generated",
                            "jobId": job_id,
                            "timestamp": datetime.utcnow().isoformat(),
                            "phase": phase,
                            "manifest": manifest_summary,
                        }
                        yield f"data: {json.dumps(candidates_event)}\n\n"

                        # Emit selection.required event
                        selection_event = {
                            "event": "selection.required",
                            "jobId": job_id,
                            "timestamp": datetime.utcnow().isoformat(),
                            "phase": phase,
                            "selectEndpoint": f"/jobs/{job_id}/select",
                            "candidatesEndpoint": f"/jobs/{job_id}/candidates",
                        }
                        yield f"data: {json.dumps(selection_event)}\n\n"
                if not paused:
                    # Reset when no longer paused so we can detect next pause
                    already_emitted_pause = None

                # Send keepalive if we had no events
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


class ValidateRequest(BaseModel):
    """Request body for timeline validation."""
    timeline_json: dict = Field(..., description="Timeline JSON to validate")


class ValidateResponse(BaseModel):
    """Response for timeline validation."""
    valid: bool
    errors: List[dict] = Field(default_factory=list)
    warnings: List[dict] = Field(default_factory=list)


@app.post("/validate")
async def validate_timeline_endpoint(request: ValidateRequest, raw_request: Request):
    """Validate a timeline document without executing it."""
    if not verify_api_key(raw_request):
        raise HTTPException(401, "Invalid or missing API key")

    # Size check
    size = len(json.dumps(request.timeline_json))
    if size > 1_048_576:  # 1MB
        raise HTTPException(413, "Timeline JSON exceeds 1MB size limit")

    from timeline.parser import parse_timeline
    from timeline.validator import validate as validate_timeline_doc

    try:
        timeline = parse_timeline(request.timeline_json)
    except Exception as e:
        return ValidateResponse(valid=False, errors=[{"path": "root", "message": str(e)}])

    result = validate_timeline_doc(timeline)
    return ValidateResponse(
        valid=result.is_valid,
        errors=[{"path": e.path, "message": e.message, "severity": e.severity} for e in result.errors],
        warnings=[{"path": w.path, "message": w.message} for w in result.warnings],
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

    output_uri = _default_output_uri()
    if not output_uri:
        raise HTTPException(500, "R2_BUCKET_NAME (or R2_OUTPUT_URI) not set")

    object_uri = f"{output_uri.rstrip('/')}/{job_id}/{file_path}"

    if not r2_storage.object_exists(object_uri):
        raise HTTPException(404, f"File not found: {job_id}/{file_path}")

    try:
        signed_url = r2_storage.generate_signed_url(object_uri)
    except Exception as e:
        raise HTTPException(500, f"Error generating signed URL: {e}")

    return RedirectResponse(url=signed_url, status_code=307)


@app.get("/download/{job_id}")
async def download_job_files(job_id: str, raw_request: Request):
    """List all files in a job's output with signed URLs."""
    if not verify_api_key(raw_request):
        raise HTTPException(401, "Invalid or missing API key")

    output_uri = _default_output_uri()
    if not output_uri:
        raise HTTPException(500, "R2_BUCKET_NAME (or R2_OUTPUT_URI) not set")

    prefix_uri = f"{output_uri.rstrip('/')}/{job_id}/"

    try:
        file_uris = r2_storage.list_files(prefix_uri)
    except Exception as e:
        raise HTTPException(500, f"Error listing files: {e}")

    if not file_uris:
        raise HTTPException(404, f"No files found for job: {job_id}")

    files = []
    for uri in file_uris:
        _, blob_path = r2_storage.parse_uri(uri)
        # Get path relative to job_id prefix
        relative_path = blob_path[len(f"{job_id}/"):]
        if not relative_path:
            continue
        try:
            signed_url = r2_storage.generate_signed_url(uri)
        except Exception as e:
            raise HTTPException(500, f"Error generating signed URL for {relative_path}: {e}")
        files.append({"path": relative_path, "url": signed_url})

    if not files:
        raise HTTPException(404, f"No files found for job: {job_id}")

    return {"job_id": job_id, "files": files}


class SelectRequest(BaseModel):
    """Request body for candidate selection during exploration mode."""
    phase: str = Field(..., description="Selection phase: images, videos, or tts")
    selections: Dict[str, List[int]] = Field(..., description="Mapping of node_id to list of selected candidate indices")


@app.post("/jobs/{job_id}/select")
async def select_candidates(job_id: str, request: SelectRequest, raw_request: Request):
    """Submit candidate selections for a paused exploration job."""
    if not verify_api_key(raw_request):
        raise HTTPException(401, "Invalid or missing API key")

    # Check job exists
    with _exploration_lock:
        state = _exploration_states.get(job_id)
        run_dir = _job_run_dirs.get(job_id)

    if not state or not run_dir:
        raise HTTPException(404, f"No active exploration job found: {job_id}")

    if state.completed:
        raise HTTPException(410, "Job has completed")

    if not state.is_paused:
        raise HTTPException(409, "Job is not currently paused for selection")

    if state.pending_phase != request.phase:
        raise HTTPException(
            400,
            f"Phase mismatch: job is waiting for '{state.pending_phase}' selections, got '{request.phase}'"
        )

    from timeline.explorer import read_manifest, validate_selections, write_selections

    # Read manifest
    manifest = read_manifest(run_dir, request.phase)
    if not manifest:
        raise HTTPException(404, f"No manifest found for phase '{request.phase}'")

    # Validate selections
    errors = validate_selections(manifest, request.selections)
    if errors:
        raise HTTPException(400, detail={"errors": errors})

    # Write selections
    try:
        write_selections(request.selections, request.phase, run_dir)
    except ValueError as e:
        raise HTTPException(409, str(e))

    # Resume execution
    state.resume()

    return {"status": "resumed", "phase": request.phase}


@app.get("/jobs/{job_id}/candidates")
async def get_candidates(job_id: str, raw_request: Request):
    """Get the current selection manifest for a paused exploration job."""
    if not verify_api_key(raw_request):
        raise HTTPException(401, "Invalid or missing API key")

    with _exploration_lock:
        state = _exploration_states.get(job_id)
        run_dir = _job_run_dirs.get(job_id)

    if not state or not run_dir:
        raise HTTPException(404, f"No active exploration job found: {job_id}")

    if state.completed:
        raise HTTPException(410, "Job has completed")

    paused, phase = state.get_pause_state()
    if not paused:
        raise HTTPException(404, "Job is not currently paused for selection")

    if not phase:
        raise HTTPException(404, "No pending selection phase")

    from timeline.explorer import read_manifest, manifest_to_dict

    manifest = read_manifest(run_dir, phase)
    if not manifest:
        raise HTTPException(404, f"No manifest found for phase '{phase}'")

    return {"job_id": job_id, **manifest_to_dict(manifest)}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
