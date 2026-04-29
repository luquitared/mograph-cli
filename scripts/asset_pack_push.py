#!/usr/bin/env python3
"""Upload a local directory as a named asset pack to GCS.

Asset packs are reusable bundles of reference images, voice samples, and
example timelines that workflows can pull on-demand instead of committing
to the repo.

Usage:
    python scripts/asset_pack_push.py <local_dir> <pack_name>

Example:
    python scripts/asset_pack_push.py runs/news-show-styles news-show-v1

GCS layout:
    gs://$GCS_OUTPUT_BUCKET/asset-packs/<pack_name>/...

Env:
    GCS_OUTPUT_BUCKET — bucket URI (e.g. gs://my-bucket)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cloudrun.gcs_storage import upload_directory


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: asset_pack_push.py <local_dir> <pack_name>", file=sys.stderr)
        return 2

    local_dir = Path(sys.argv[1]).resolve()
    pack_name = sys.argv[2]

    if not local_dir.is_dir():
        print(f"not a directory: {local_dir}", file=sys.stderr)
        return 2

    bucket = os.environ.get("GCS_OUTPUT_BUCKET", "").rstrip("/")
    if not bucket:
        print("GCS_OUTPUT_BUCKET not set", file=sys.stderr)
        return 2
    if not bucket.startswith("gs://"):
        bucket = f"gs://{bucket}"

    base_uri = f"{bucket}/asset-packs/{pack_name}"
    print(f"[push] {local_dir} → {base_uri}", file=sys.stderr)

    result = upload_directory(local_dir, base_uri, pattern="**/*")
    uris = result.get("gcs_uris", [])
    print(f"[OK] uploaded {len(uris)} files to {base_uri}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
