"""Google Cloud Storage integration for Cloud Run pipeline.

Handles uploading/downloading files to/from GCS buckets for:
- Input: brand images, reference images, script files
- Output: generated images, videos, audio, final video
"""

import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional
from google.cloud import storage


_gcs_client = None


def get_gcs_client() -> storage.Client:
    """Get authenticated GCS client."""
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client()
    return _gcs_client


def parse_gcs_uri(uri: str) -> tuple[str, str]:
    """Parse gs://bucket/path into (bucket, path)."""
    if not uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {uri}")
    parts = uri[5:].split("/", 1)
    bucket = parts[0]
    path = parts[1] if len(parts) > 1 else ""
    return bucket, path


def download_file(gcs_uri: str, local_path: Path) -> Path:
    """Download a file from GCS to local path."""
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI (must start with gs://): {gcs_uri}")

    client = get_gcs_client()
    bucket_name, blob_path = parse_gcs_uri(gcs_uri)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    local_path.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(local_path))
    return local_path


def download_files(gcs_uris: List[str], local_dir: Path) -> List[Path]:
    """Download multiple files from GCS, preserving filenames."""
    local_paths = []
    for uri in gcs_uris:
        _, blob_path = parse_gcs_uri(uri)
        filename = Path(blob_path).name
        local_path = local_dir / filename
        download_file(uri, local_path)
        local_paths.append(local_path)
    return local_paths


def upload_file(local_path: Path, gcs_uri: str) -> str:
    """Upload a local file to GCS."""
    client = get_gcs_client()
    bucket_name, blob_path = parse_gcs_uri(gcs_uri)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    blob.upload_from_filename(str(local_path))
    return gcs_uri


def generate_signed_url(gcs_uri: str, expiration_hours: int = 24) -> str:
    """Generate a signed URL for a GCS object.

    Args:
        gcs_uri: GCS URI (gs://bucket/path)
        expiration_hours: Hours until URL expires (default 24)

    Returns:
        Signed HTTPS URL that can be accessed without authentication
    """
    client = get_gcs_client()
    bucket_name, blob_path = parse_gcs_uri(gcs_uri)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(hours=expiration_hours),
        method="GET",
    )
    return url


def _get_signing_credentials():
    """Get credentials that can sign URLs (for Cloud Run environment)."""
    import google.auth
    from google.auth import compute_engine
    from google.auth.transport import requests

    credentials, project = google.auth.default()

    # If running on Cloud Run/Compute Engine, we need to use IAM signing
    if isinstance(credentials, compute_engine.Credentials):
        # Get the service account email
        auth_request = requests.Request()
        credentials.refresh(auth_request)

        # Create signing credentials using IAM API
        from google.auth import iam
        from google.auth.transport import requests as auth_requests

        signer = iam.Signer(
            auth_requests.Request(),
            credentials,
            credentials.service_account_email,
        )

        signing_credentials = compute_engine.IDTokenCredentials(
            auth_requests.Request(),
            target_audience="",
            service_account_email=credentials.service_account_email,
        )
        # Return the email for signing
        return credentials.service_account_email, credentials

    return None, credentials


def upload_directory(local_dir: Path, gcs_base_uri: str, pattern: str = "**/*") -> Dict[str, List[str]]:
    """Upload all files in a directory to GCS.

    Returns:
        Dict with 'gcs_uris' (gs:// paths) and 'signed_urls' (https:// accessible URLs)
    """
    import google.auth
    from google.auth import compute_engine
    from google.auth.transport import requests

    client = get_gcs_client()
    bucket_name, base_path = parse_gcs_uri(gcs_base_uri)
    bucket = client.bucket(bucket_name)

    gcs_uris = []
    signed_urls = []

    for local_path in local_dir.glob(pattern):
        if local_path.is_file():
            relative = local_path.relative_to(local_dir)
            blob_path = f"{base_path}/{relative}" if base_path else str(relative)
            blob = bucket.blob(blob_path)
            blob.upload_from_filename(str(local_path))

            gcs_uri = f"gs://{bucket_name}/{blob_path}"
            gcs_uris.append(gcs_uri)

            # Generate public URL (bucket must have public access enabled)
            public_url = f"https://storage.googleapis.com/{bucket_name}/{blob_path}"
            signed_urls.append(public_url)

    return {"gcs_uris": gcs_uris, "signed_urls": signed_urls}


def list_files(gcs_uri: str, pattern: Optional[str] = None) -> List[str]:
    """List files in a GCS path."""
    client = get_gcs_client()
    bucket_name, prefix = parse_gcs_uri(gcs_uri)
    bucket = client.bucket(bucket_name)

    blobs = bucket.list_blobs(prefix=prefix)
    uris = [f"gs://{bucket_name}/{blob.name}" for blob in blobs]

    if pattern:
        import fnmatch
        uris = [uri for uri in uris if fnmatch.fnmatch(uri, pattern)]

    return uris


def ensure_bucket_exists(bucket_name: str, location: str = "us-central1") -> None:
    """Create bucket if it doesn't exist."""
    client = get_gcs_client()
    bucket = client.bucket(bucket_name)

    if not bucket.exists():
        bucket.create(location=location)


class GCSWorkspace:
    """Manages a temporary local workspace with GCS sync capabilities."""

    def __init__(self, gcs_output_uri: Optional[str] = None, local_base: Optional[Path] = None):
        self.gcs_output_uri = gcs_output_uri
        self.is_local_only = gcs_output_uri is None
        # Track if we created a temp directory (so we know to clean it up)
        self._is_temp_dir = local_base is None
        self.local_base = local_base or Path(tempfile.mkdtemp(prefix="cloudrun_"))
        self.local_base.mkdir(parents=True, exist_ok=True)

    @property
    def output_uri(self) -> Optional[str]:
        """Alias for gcs_output_uri. None in local-only mode."""
        return self.gcs_output_uri

    @property
    def runs_dir(self) -> Path:
        runs = self.local_base / "runs"
        runs.mkdir(exist_ok=True)
        return runs

    @property
    def inputs_dir(self) -> Path:
        inputs = self.local_base / "inputs"
        inputs.mkdir(exist_ok=True)
        return inputs

    def download_inputs(
        self,
        reference_images: List[str],
        main_ref: Optional[str] = None,
        timeline_file: Optional[str] = None,
        voice_file: Optional[str] = None,
    ) -> dict:
        """Download input files from GCS and return local paths."""
        result = {"reference_images": [], "main_ref": None, "timeline_file": None, "voice_file": None}

        if reference_images:
            ref_dir = self.inputs_dir / "brand"  # Keep dir name for backwards compat
            ref_dir.mkdir(exist_ok=True)
            result["reference_images"] = download_files(reference_images, ref_dir)

        if main_ref:
            main_ref_path = self.inputs_dir / "main_ref" / Path(main_ref).name
            download_file(main_ref, main_ref_path)
            result["main_ref"] = main_ref_path

        if timeline_file:
            timeline_path = self.inputs_dir / "timeline.json"
            download_file(timeline_file, timeline_path)
            result["timeline_file"] = timeline_path

        if voice_file:
            # Preserve original extension (mp3, wav, m4a, etc.)
            voice_ext = Path(voice_file).suffix or ".m4a"
            voice_path = self.inputs_dir / f"voice{voice_ext}"
            download_file(voice_file, voice_path)
            result["voice_file"] = voice_path

        return result

    def upload_outputs(self, run_dir: Path, job_id: Optional[str] = None) -> dict:
        """Upload run outputs to GCS and return URIs. In local-only mode, just return local paths.

        Args:
            run_dir: Local directory containing the run outputs
            job_id: Optional job/generation ID to use as the GCS folder name (defaults to run_dir.name)
        """
        # Use job_id if provided, otherwise fall back to run directory name
        output_folder = job_id or run_dir.name

        if self.is_local_only:
            # Local-only mode: return local paths
            local_files = [str(p) for p in run_dir.glob("**/*") if p.is_file()]
            return {
                "gcs_base": str(run_dir),
                "files": local_files,
                "signed_urls": local_files,  # Same as files in local mode
                "run_name": output_folder,
                "local_only": True,
            }

        # Build GCS path with job_id/run_name as subfolder
        gcs_output_path = f"{self.gcs_output_uri.rstrip('/')}/{output_folder}"
        upload_result = upload_directory(run_dir, gcs_output_path)
        return {
            "gcs_base": gcs_output_path,
            "files": upload_result["gcs_uris"],
            "signed_urls": upload_result["signed_urls"],
            "run_name": output_folder,
        }

    def cleanup(self) -> None:
        """Remove temporary local files. Only cleans up auto-created temp directories."""
        import shutil
        # Only delete if we created a temp directory, not user-specified directories
        if self._is_temp_dir and self.local_base.exists():
            shutil.rmtree(self.local_base)
