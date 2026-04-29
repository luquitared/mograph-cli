#!/usr/bin/env python3
"""Upload a local directory as a named pack to GCS.

Packs are reusable bundles workflows can pull on-demand instead of
committing to the repo. Two pack types today:

- `asset-packs` (default) — character sheets, voice samples, environment
  refs for a workflow (e.g. `news-show-v1`)
- `style-packs` — source video + extracted frames + style.json for the
  style-rip workflow (use `--prefix style-packs`)

Usage:
    python scripts/asset_pack_push.py <local_dir> <pack_name> [--prefix <prefix>]

Examples:
    # Asset pack (default prefix)
    python scripts/asset_pack_push.py runs/asset-packs/news-show-v1 news-show-v1

    # Style pack
    python scripts/asset_pack_push.py runs/style-packs/ig-DW2FRgojpMa ig-DW2FRgojpMa --prefix style-packs

GCS layout:
    gs://$GCS_OUTPUT_BUCKET/<prefix>/<pack_name>/...

Env:
    GCS_OUTPUT_BUCKET — bucket URI (e.g. gs://my-bucket)
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cloudrun.gcs_storage import upload_directory


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload a local directory as a named pack to GCS")
    ap.add_argument("local_dir", help="Local directory to upload")
    ap.add_argument("pack_name", help="Pack name (becomes the GCS folder name)")
    ap.add_argument("--prefix", default="asset-packs",
                    help="GCS path component (default: asset-packs). Use 'style-packs' for style-rip packs.")
    args = ap.parse_args()

    local_dir = Path(args.local_dir).resolve()
    pack_name = args.pack_name
    prefix = args.prefix.strip("/")

    if not local_dir.is_dir():
        print(f"not a directory: {local_dir}", file=sys.stderr)
        return 2

    bucket = os.environ.get("GCS_OUTPUT_BUCKET", "").rstrip("/")
    if not bucket:
        print("GCS_OUTPUT_BUCKET not set", file=sys.stderr)
        return 2
    if not bucket.startswith("gs://"):
        bucket = f"gs://{bucket}"

    base_uri = f"{bucket}/{prefix}/{pack_name}"
    print(f"[push] {local_dir} → {base_uri}", file=sys.stderr)

    result = upload_directory(local_dir, base_uri, pattern="**/*")
    uris = result.get("gcs_uris", [])
    print(f"[OK] uploaded {len(uris)} files to {base_uri}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
