"""Cloudflare R2 storage integration for the Cloud Run pipeline.

R2 speaks S3 over HTTPS, so this uses boto3 against the R2 S3-compat
endpoint.

Required environment:
    R2_ACCOUNT_ID
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
    R2_BUCKET_NAME (default bucket — used when a URI omits the bucket)

URI schemes accepted by `parse_uri`:
    r2://bucket/path    (preferred)
    s3://bucket/path    (interchangeable)
    gs://bucket/path    (legacy — kept for back-compat with timeline JSON
                         and prior asset packs)
"""

from __future__ import annotations

import mimetypes
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import boto3
from botocore.client import Config

_client = None
_default_bucket: Optional[str] = None


def get_client():
    """Boto3 S3 client wired against the R2 endpoint."""
    global _client
    if _client is not None:
        return _client
    account_id = os.environ.get("R2_ACCOUNT_ID")
    if not account_id:
        raise RuntimeError("R2_ACCOUNT_ID is not set")
    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", region_name="auto"),
    )
    return _client


def get_default_bucket() -> str:
    global _default_bucket
    if _default_bucket is None:
        name = os.environ.get("R2_BUCKET_NAME") or os.environ.get("R2_BUCKET")
        if not name:
            raise RuntimeError("R2_BUCKET_NAME is not set")
        _default_bucket = name.strip().lstrip("/").rstrip("/")
    return _default_bucket


def parse_uri(uri: str) -> Tuple[str, str]:
    """Parse r2:// / s3:// / gs:// URI into (bucket, key).

    A bare path (no scheme, no slash prefix) is treated as a key inside the
    default bucket — handy when callers compose paths and the bucket is fixed.
    """
    for scheme in ("r2://", "s3://", "gs://"):
        if uri.startswith(scheme):
            rest = uri[len(scheme):]
            parts = rest.split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
            return bucket, key
    # No scheme — treat as a relative key inside the default bucket.
    return get_default_bucket(), uri.lstrip("/")


def _content_type(path: Path) -> Optional[str]:
    ct, _ = mimetypes.guess_type(str(path))
    return ct


def download_file(uri: str, local_path: Path) -> Path:
    """Download a single object to a local path."""
    bucket, key = parse_uri(uri)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    get_client().download_file(bucket, key, str(local_path))
    return local_path


def download_files(uris: List[str], local_dir: Path) -> List[Path]:
    local_paths: List[Path] = []
    for uri in uris:
        _, key = parse_uri(uri)
        dest = local_dir / Path(key).name
        download_file(uri, dest)
        local_paths.append(dest)
    return local_paths


def upload_file(local_path: Path, uri: str, content_type: Optional[str] = None) -> str:
    """Upload a single file and return the canonical r2:// URI it landed at."""
    bucket, key = parse_uri(uri)
    ct = content_type or _content_type(local_path)
    extra = {"ContentType": ct} if ct else {}
    get_client().upload_file(str(local_path), bucket, key, ExtraArgs=extra)
    return f"r2://{bucket}/{key}"


def generate_signed_url(uri: str, expiration_hours: int = 24) -> str:
    """Presigned GET URL good for `expiration_hours` hours."""
    bucket, key = parse_uri(uri)
    return get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=int(timedelta(hours=expiration_hours).total_seconds()),
    )


def upload_directory(
    local_dir: Path,
    base_uri: str,
    pattern: str = "**/*",
    signed_url_hours: int = 24 * 7,
) -> Dict[str, List[str]]:
    """Recursively upload everything under `local_dir` to `base_uri`.

    Returns a dict with:
      uris        — r2:// URIs of each uploaded object
      signed_urls — presigned GET URLs valid for `signed_url_hours`
    """
    bucket, base_key = parse_uri(base_uri)
    base_key = base_key.rstrip("/")

    uris: List[str] = []
    signed: List[str] = []
    client = get_client()

    for local_path in sorted(local_dir.glob(pattern)):
        if not local_path.is_file():
            continue
        rel = local_path.relative_to(local_dir).as_posix()
        key = f"{base_key}/{rel}" if base_key else rel
        ct = _content_type(local_path)
        client.upload_file(
            str(local_path),
            bucket,
            key,
            ExtraArgs={"ContentType": ct} if ct else {},
        )
        uris.append(f"r2://{bucket}/{key}")
        signed.append(
            client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=int(timedelta(hours=signed_url_hours).total_seconds()),
            )
        )

    return {"uris": uris, "signed_urls": signed}


def list_files(uri: str, pattern: Optional[str] = None) -> List[str]:
    """List object URIs under `uri` (a prefix). Optional fnmatch pattern filter."""
    bucket, prefix = parse_uri(uri)
    client = get_client()
    uris: List[str] = []
    continuation_token: Optional[str] = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        resp = client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []) or []:
            uris.append(f"r2://{bucket}/{obj['Key']}")
        if not resp.get("IsTruncated"):
            break
        continuation_token = resp.get("NextContinuationToken")

    if pattern:
        import fnmatch
        uris = [u for u in uris if fnmatch.fnmatch(u, pattern)]
    return uris


def object_exists(uri: str) -> bool:
    bucket, key = parse_uri(uri)
    try:
        get_client().head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


class R2Workspace:
    """Local temp workspace synced to an R2 prefix.

    `output_uri` may be `r2://...`, `s3://...`, `gs://...` (still parsed for
    timeline JSON written before the R2 migration), or `None` for local-only
    test runs.
    """

    def __init__(
        self,
        output_uri: Optional[str] = None,
        local_base: Optional[Path] = None,
    ):
        self.output_uri = output_uri
        self.is_local_only = output_uri is None
        self._is_temp_dir = local_base is None
        self.local_base = local_base or Path(tempfile.mkdtemp(prefix="cloudrun_"))
        self.local_base.mkdir(parents=True, exist_ok=True)

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
        result = {
            "reference_images": [],
            "main_ref": None,
            "timeline_file": None,
            "voice_file": None,
        }

        if reference_images:
            ref_dir = self.inputs_dir / "brand"
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
            voice_ext = Path(voice_file).suffix or ".m4a"
            voice_path = self.inputs_dir / f"voice{voice_ext}"
            download_file(voice_file, voice_path)
            result["voice_file"] = voice_path

        return result

    def upload_outputs(self, run_dir: Path, job_id: Optional[str] = None) -> dict:
        output_folder = job_id or run_dir.name

        if self.is_local_only:
            local_files = [str(p) for p in run_dir.glob("**/*") if p.is_file()]
            return {
                "output_base": str(run_dir),
                "files": local_files,
                "signed_urls": local_files,
                "run_name": output_folder,
                "local_only": True,
            }

        output_path = f"{self.output_uri.rstrip('/')}/{output_folder}"
        upload_result = upload_directory(run_dir, output_path)
        return {
            "output_base": output_path,
            "files": upload_result["uris"],
            "signed_urls": upload_result["signed_urls"],
            "run_name": output_folder,
        }

    def cleanup(self) -> None:
        import shutil
        if self._is_temp_dir and self.local_base.exists():
            shutil.rmtree(self.local_base)
