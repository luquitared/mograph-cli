#!/usr/bin/env python3
"""Batch submit video generation jobs to Cloud Run and download results.

Usage:
    # Simple - use config file
    python batch_cloudrun.py --config batch_config.json --timelines-dir ./timelines

    # Without config file (all args required)
    python batch_cloudrun.py --timelines-dir ./timelines --service-url https://... --output-bucket my-bucket

Config file format (batch_config.json):
    {
        "service_url": "https://your-service.run.app",
        "output_bucket": "your-bucket-name",
        "service_account_key": "./service-account.json",
        "defaults": {
            "stage": "final",
            "concurrency": 5,
            "mock": false
        }
    }
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp
from dotenv import load_dotenv
from google.cloud import storage
import google.auth
import google.auth.transport.requests
from google.oauth2 import id_token

# Load environment variables
load_dotenv()


@dataclass
class BatchConfig:
    """Configuration for batch processing."""
    service_url: str = ""
    output_bucket: str = ""
    service_account_key: Optional[str] = None
    api_key: str = ""
    output_dir: Path = field(default_factory=lambda: Path("./batch_output"))

    # Default pipeline settings
    stage: str = "final"
    concurrency: int = 5
    poll_interval: float = 15.0
    mock: bool = False

    @classmethod
    def from_file(cls, config_path: Path) -> "BatchConfig":
        """Load config from JSON file."""
        with open(config_path) as f:
            data = json.load(f)

        config = cls()

        # Top-level settings
        config.service_url = data.get("service_url", config.service_url)
        # Strip gs:// prefix if provided
        bucket = data.get("output_bucket", config.output_bucket)
        config.output_bucket = bucket.removeprefix("gs://") if bucket else ""
        config.service_account_key = data.get("service_account_key", config.service_account_key)
        config.api_key = data.get("api_key", config.api_key)
        if "output_dir" in data:
            config.output_dir = Path(data["output_dir"])

        # Defaults section
        defaults = data.get("defaults", {})
        config.stage = defaults.get("stage", config.stage)
        config.concurrency = defaults.get("concurrency", config.concurrency)
        config.poll_interval = defaults.get("poll_interval", config.poll_interval)
        config.mock = defaults.get("mock", config.mock)

        return config

    def merge_cli_args(self, args: argparse.Namespace) -> None:
        """Override config with CLI arguments (if provided)."""
        if args.service_url:
            self.service_url = args.service_url
        if args.output_bucket:
            # Strip gs:// prefix if provided
            self.output_bucket = args.output_bucket.removeprefix("gs://")
        if args.service_account_key:
            self.service_account_key = args.service_account_key
        if args.api_key:
            self.api_key = args.api_key
        if args.output_dir:
            self.output_dir = args.output_dir
        if args.stage:
            self.stage = args.stage
        if args.concurrency:
            self.concurrency = args.concurrency
        if hasattr(args, 'poll_interval') and args.poll_interval:
            self.poll_interval = args.poll_interval
        if hasattr(args, 'mock') and args.mock:
            self.mock = args.mock


def validate_timelines(timeline_files: list[Path]) -> list[dict]:
    """Validate timeline files and return warnings/errors for any issues.

    Args:
        timeline_files: List of timeline file paths to validate

    Returns:
        List of warning/error dicts

    Raises:
        ValueError: If any timeline files have errors
    """
    errors = []

    for timeline_path in timeline_files:
        try:
            with open(timeline_path) as f:
                timeline_data = json.load(f)
        except json.JSONDecodeError as e:
            errors.append({"timeline": timeline_path.name, "error": f"Invalid JSON: {e}"})
            continue

        # Check required fields (timeline format)
        if not timeline_data.get("tracks"):
            errors.append({"timeline": timeline_path.name, "error": "No tracks defined (expected timeline format)"})

    if errors:
        error_msgs = []
        for e in errors:
            error_msgs.append(f"[{e['timeline']}] {e['error']}")
        raise ValueError(
            "Timeline validation failed:\n" + "\n".join(f"  - {m}" for m in error_msgs)
        )

    return []


def get_identity_token(audience: str, service_account_file: Optional[str] = None) -> str:
    """Get a Google Cloud identity token for Cloud Run authentication."""
    from google.oauth2 import service_account as sa_module

    # Check for service account file
    sa_file = service_account_file or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if sa_file and Path(sa_file).exists():
        # Use service account credentials to get ID token
        credentials = sa_module.IDTokenCredentials.from_service_account_file(
            sa_file,
            target_audience=audience,
        )
        request = google.auth.transport.requests.Request()
        credentials.refresh(request)
        return credentials.token

    # Fallback: try default credentials
    request = google.auth.transport.requests.Request()
    try:
        token = id_token.fetch_id_token(request, audience)
        return token
    except Exception:
        # Last resort: use gcloud command
        import subprocess
        result = subprocess.run(
            ["gcloud", "auth", "print-identity-token"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        raise RuntimeError(f"Failed to get identity token: {result.stderr}")


@dataclass
class JobMetrics:
    """Metrics for a single job."""
    job_id: str
    timeline_file: str
    status: str = "pending"
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    output_uri: Optional[str] = None
    error: Optional[str] = None
    files_downloaded: int = 0

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None


@dataclass
class BatchMetrics:
    """Overall batch metrics."""
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    jobs: list[JobMetrics] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    def summary(self) -> str:
        lines = [
            "",
            "=" * 60,
            "BATCH GENERATION SUMMARY",
            "=" * 60,
            f"Total jobs:     {self.total_jobs}",
            f"Completed:      {self.completed_jobs}",
            f"Failed:         {self.failed_jobs}",
            f"Total duration: {self.duration_seconds:.1f}s ({self.duration_seconds/60:.1f} min)",
            "",
            "Per-job breakdown:",
            "-" * 60,
        ]

        for job in self.jobs:
            status_icon = "+" if job.status == "completed" else "x"
            duration_str = f"{job.duration_seconds:.1f}s" if job.duration_seconds else "N/A"
            lines.append(f"  [{status_icon}] {Path(job.timeline_file).name}: {job.status} ({duration_str})")
            if job.error:
                lines.append(f"      Error: {job.error[:100]}...")
            if job.files_downloaded > 0:
                lines.append(f"      Downloaded: {job.files_downloaded} files")

        lines.append("=" * 60)

        # Calculate average duration for successful jobs
        successful_durations = [j.duration_seconds for j in self.jobs if j.duration_seconds and j.status == "completed"]
        if successful_durations:
            avg_duration = sum(successful_durations) / len(successful_durations)
            lines.append(f"Avg job duration: {avg_duration:.1f}s")

        return "\n".join(lines)


class BatchCloudRunClient:
    """Client for batch submitting jobs to Cloud Run."""

    def __init__(
        self,
        service_url: str,
        api_key: str,
        output_bucket: str,
        concurrency: int = 10,
        poll_interval: float = 10.0,
        service_account_key: Optional[str] = None,
        local: bool = False,
    ):
        self.service_url = service_url.rstrip("/")
        self.api_key = api_key
        # Strip gs:// prefix if provided (code adds it automatically)
        self.output_bucket = output_bucket.removeprefix("gs://")
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.semaphore = asyncio.Semaphore(concurrency)
        self.metrics = BatchMetrics()
        self.service_account_key = service_account_key
        self._storage_client = None
        self.local = local

        # Get identity token for Cloud Run IAM authentication (skip for local)
        if local:
            print("Running in local mode (skipping identity token)")
            self.identity_token = None
        else:
            print("Fetching Google Cloud identity token...")
            self.identity_token = get_identity_token(self.service_url, service_account_key)
            print("Identity token obtained successfully")

    def _get_storage_client(self):
        """Get or create a GCS storage client."""
        if self._storage_client is None:
            if self.service_account_key:
                self._storage_client = storage.Client.from_service_account_json(self.service_account_key)
            else:
                self._storage_client = storage.Client()
        return self._storage_client

    async def _make_request(
        self,
        session: aiohttp.ClientSession,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """Make an authenticated request to the Cloud Run service."""
        url = f"{self.service_url}{endpoint}"
        headers = kwargs.pop("headers", {})
        # Use identity token for Cloud Run IAM auth (skip for local)
        if self.identity_token:
            headers["Authorization"] = f"Bearer {self.identity_token}"
        # Also include API key for application-level auth
        headers["X-API-Key"] = self.api_key
        headers["Content-Type"] = "application/json"

        async with session.request(method, url, headers=headers, **kwargs) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {text[:500]}")
            return await resp.json()

    async def submit_job(
        self,
        session: aiohttp.ClientSession,
        timeline_path: Path,
        job_metrics: JobMetrics,
        config: BatchConfig,
    ) -> str:
        """Submit a single job and return the payload."""
        with open(timeline_path) as f:
            timeline_json = json.load(f)

        # Generate unique output path
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        timeline_name = timeline_path.stem
        output_uri = f"gs://{self.output_bucket}/batch-runs/{timestamp}/{timeline_name}"

        payload = {
            "timeline_json": timeline_json,
            "output_uri": output_uri,
            "stage": config.stage,
            "mock": config.mock,
        }

        job_metrics.start_time = time.time()
        job_metrics.output_uri = output_uri
        return payload

    async def poll_job_status(
        self,
        session: aiohttp.ClientSession,
        job_id: str,
    ) -> dict:
        """Poll for job status."""
        return await self._make_request(session, "GET", f"/status/{job_id}")

    async def wait_for_job(
        self,
        session: aiohttp.ClientSession,
        job_id: str,
        job_metrics: JobMetrics,
    ) -> dict:
        """Wait for a job to complete."""
        while True:
            status = await self.poll_job_status(session, job_id)
            job_metrics.status = status["status"]

            if status["status"] in ("completed", "failed"):
                job_metrics.end_time = time.time()
                if status["status"] == "failed":
                    job_metrics.error = status.get("error", "Unknown error")
                return status

            await asyncio.sleep(self.poll_interval)

    async def process_timeline(
        self,
        session: aiohttp.ClientSession,
        timeline_path: Path,
        config: BatchConfig,
    ) -> JobMetrics:
        """Process a single timeline file (submit and wait for sync response)."""
        job_metrics = JobMetrics(job_id="", timeline_file=str(timeline_path))

        async with self.semaphore:
            try:
                print(f"[START]  {timeline_path.name}")

                # Build payload
                payload = await self.submit_job(session, timeline_path, job_metrics, config)

                # Make synchronous request (waits for completion)
                result = await self._make_request(session, "POST", "/generate", json=payload)

                job_metrics.end_time = time.time()
                job_metrics.job_id = result.get("job_id", "")
                job_metrics.status = "completed"
                print(f"[DONE]   {timeline_path.name} ({job_metrics.duration_seconds:.1f}s)")
                self.metrics.completed_jobs += 1

            except Exception as e:
                job_metrics.status = "failed"
                job_metrics.error = str(e)
                job_metrics.end_time = time.time()
                print(f"[ERROR]  {timeline_path.name}: {e}")
                self.metrics.failed_jobs += 1

        return job_metrics

    async def run_batch(
        self,
        timeline_files: list[Path],
        config: BatchConfig,
    ) -> BatchMetrics:
        """Run batch processing for all timeline files."""
        self.metrics = BatchMetrics(total_jobs=len(timeline_files))

        print(f"\nStarting batch of {len(timeline_files)} jobs (concurrency={self.concurrency})")
        print(f"Output bucket: gs://{self.output_bucket}/batch-runs/")
        print(f"Stage: {config.stage}")
        if config.mock:
            print(f"Mock mode: enabled (using test fixtures)")
        print("-" * 60)

        timeout = aiohttp.ClientTimeout(total=900)  # 15 min per job (sync mode waits for completion)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = [
                self.process_timeline(session, timeline, config)
                for timeline in timeline_files
            ]
            job_metrics_list = await asyncio.gather(*tasks)
            self.metrics.jobs = list(job_metrics_list)

        self.metrics.end_time = time.time()
        return self.metrics


def download_from_gcs(
    output_bucket: str,
    local_output_dir: Path,
    job_metrics_list: list[JobMetrics],
    service_account_key: Optional[str] = None,
) -> None:
    """Download all completed job outputs from GCS."""
    if service_account_key:
        client = storage.Client.from_service_account_json(service_account_key)
    else:
        client = storage.Client()
    bucket = client.bucket(output_bucket)

    print(f"\nDownloading results to {local_output_dir}")
    print("-" * 60)

    for job in job_metrics_list:
        if job.status != "completed" or not job.output_uri:
            continue

        # Parse output URI to get prefix
        prefix = job.output_uri.replace(f"gs://{output_bucket}/", "")

        # Create local directory for this job
        timeline_name = Path(job.timeline_file).stem
        job_dir = local_output_dir / timeline_name
        job_dir.mkdir(parents=True, exist_ok=True)

        # List and download all blobs with this prefix
        blobs = list(bucket.list_blobs(prefix=prefix))
        print(f"[DOWNLOAD] {timeline_name}: {len(blobs)} files")

        for blob in blobs:
            # Compute relative path from prefix
            relative_path = blob.name[len(prefix):].lstrip("/")
            if not relative_path:
                continue

            local_path = job_dir / relative_path
            local_path.parent.mkdir(parents=True, exist_ok=True)

            blob.download_to_filename(str(local_path))
            job.files_downloaded += 1

        print(f"[DONE]     {timeline_name}: downloaded to {job_dir}")


def find_timeline_files(timelines_dir: Path) -> list[Path]:
    """Find all timeline JSON files in a directory."""
    if not timelines_dir.exists():
        raise FileNotFoundError(f"Timelines directory not found: {timelines_dir}")

    # Find all .json files
    json_files = list(timelines_dir.glob("*.json"))

    # Filter to timeline format files (have 'project' and 'tracks' keys)
    filtered = []
    for f in json_files:
        try:
            with open(f) as fp:
                data = json.load(fp)
                if "project" in data and "tracks" in data:
                    filtered.append(f)
        except (json.JSONDecodeError, KeyError):
            pass

    return sorted(filtered)


def main():
    parser = argparse.ArgumentParser(
        description="Batch submit video generation jobs to Cloud Run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using config file (recommended)
  python batch_cloudrun.py --config batch_config.json --timelines-dir ./timelines

  # Without config file
  python batch_cloudrun.py --timelines-dir ./timelines --service-url https://... --output-bucket my-bucket
        """,
    )

    # Config file (recommended)
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to batch config JSON file (simplifies CLI usage)",
    )

    # Required
    parser.add_argument(
        "--timelines-dir",
        type=Path,
        required=True,
        help="Directory containing timeline JSON files",
    )

    # Override options (optional when using --config)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Local directory to download results (default: ./batch_output)",
    )
    parser.add_argument(
        "--service-url",
        type=str,
        default=os.environ.get("CLOUDRUN_SERVICE_URL", ""),
        help="Cloud Run service URL (or set CLOUDRUN_SERVICE_URL)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API key for Cloud Run service",
    )
    parser.add_argument(
        "--output-bucket",
        type=str,
        default=os.environ.get("GCS_OUTPUT_BUCKET", ""),
        help="GCS bucket for outputs (or set GCS_OUTPUT_BUCKET)",
    )
    parser.add_argument(
        "--service-account-key",
        type=str,
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        help="Path to GCS service account key JSON file",
    )

    # Pipeline defaults
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Number of concurrent jobs (default: 5)",
    )
    parser.add_argument(
        "--stage",
        choices=["images", "videos", "final"],
        default=None,
        help="Pipeline stage (default: final)",
    )

    # Flags
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip downloading results from GCS",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate timelines and show what would be processed",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate timeline files",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock fixtures instead of real API calls (for fast testing)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run against local server (skip Google identity token)",
    )

    args = parser.parse_args()

    # Load config from file or create defaults
    if args.config:
        if not args.config.exists():
            print(f"Error: Config file not found: {args.config}")
            sys.exit(1)
        config = BatchConfig.from_file(args.config)
        print(f"Loaded config from {args.config}")
    else:
        config = BatchConfig()

    # Apply CLI overrides
    config.merge_cli_args(args)

    # Handle output_dir default
    if args.output_dir:
        config.output_dir = args.output_dir

    # Validate required settings
    if not config.service_url:
        print("Error: --service-url required (or use --config file or set CLOUDRUN_SERVICE_URL)")
        sys.exit(1)
    if not config.output_bucket:
        print("Error: --output-bucket required (or use --config file or set GCS_OUTPUT_BUCKET)")
        sys.exit(1)

    # Find timeline files
    timeline_files = find_timeline_files(args.timelines_dir)
    if not timeline_files:
        print(f"No timeline files found in {args.timelines_dir}")
        sys.exit(1)

    print(f"Found {len(timeline_files)} timeline files:")
    for f in timeline_files:
        print(f"  - {f.name}")

    # Validate timelines
    try:
        validate_timelines(timeline_files)
    except ValueError as e:
        print(f"\n{e}")
        sys.exit(1)

    if args.validate_only:
        print("All timelines validated successfully.")
        sys.exit(0)

    if args.dry_run:
        print(f"\n[DRY RUN] Configuration:")
        print(f"  service_url: {config.service_url}")
        print(f"  output_bucket: {config.output_bucket}")
        print(f"  stage: {config.stage}")
        print(f"  mock: {config.mock}")
        print(f"\nWould process {len(timeline_files)} timelines. Exiting.")
        sys.exit(0)

    # Create output directory
    config.output_dir.mkdir(parents=True, exist_ok=True)

    # Run batch
    client = BatchCloudRunClient(
        service_url=config.service_url,
        api_key=config.api_key,
        output_bucket=config.output_bucket,
        concurrency=config.concurrency,
        poll_interval=config.poll_interval,
        service_account_key=config.service_account_key,
        local=args.local,
    )

    metrics = asyncio.run(client.run_batch(timeline_files, config))

    # Download results
    if not args.skip_download:
        download_from_gcs(config.output_bucket, config.output_dir, metrics.jobs, config.service_account_key)

    # Print summary
    print(metrics.summary())

    # Save metrics to file
    metrics_file = config.output_dir / "batch_metrics.json"
    metrics_data = {
        "total_jobs": metrics.total_jobs,
        "completed_jobs": metrics.completed_jobs,
        "failed_jobs": metrics.failed_jobs,
        "duration_seconds": metrics.duration_seconds,
        "config": {
            "service_url": config.service_url,
            "output_bucket": config.output_bucket,
            "stage": config.stage,
            "mock": config.mock,
        },
        "jobs": [
            {
                "job_id": j.job_id,
                "timeline_file": j.timeline_file,
                "status": j.status,
                "duration_seconds": j.duration_seconds,
                "output_uri": j.output_uri,
                "error": j.error,
                "files_downloaded": j.files_downloaded,
            }
            for j in metrics.jobs
        ],
    }
    with open(metrics_file, "w") as f:
        json.dump(metrics_data, f, indent=2)
    print(f"\nMetrics saved to {metrics_file}")

    # Exit with error code if any jobs failed
    if metrics.failed_jobs > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
