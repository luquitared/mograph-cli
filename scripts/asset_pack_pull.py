#!/usr/bin/env python3
"""Download a named asset pack from GCS to a local directory.

Mirror of asset_pack_push.py. Pulls everything under
gs://$GCS_OUTPUT_BUCKET/asset-packs/<pack_name>/ to <dest_dir>/<pack_name>/,
preserving the relative directory structure.

Usage:
    python scripts/asset_pack_pull.py <pack_name> [<dest_dir>]

Example:
    python scripts/asset_pack_pull.py news-show-v1
    python scripts/asset_pack_pull.py news-show-v1 ./my-assets
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cloudrun.gcs_storage import download_file, list_files, parse_gcs_uri


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: asset_pack_pull.py <pack_name> [<dest_dir>]", file=sys.stderr)
        return 2

    pack_name = sys.argv[1]
    dest_root = Path(sys.argv[2]).resolve() if len(sys.argv) >= 3 else (
        Path(__file__).resolve().parent.parent / "runs" / "asset-packs"
    )
    dest_dir = dest_root / pack_name

    bucket = os.environ.get("GCS_OUTPUT_BUCKET", "").rstrip("/")
    if not bucket:
        print("GCS_OUTPUT_BUCKET not set", file=sys.stderr)
        return 2
    if not bucket.startswith("gs://"):
        bucket = f"gs://{bucket}"

    base_uri = f"{bucket}/asset-packs/{pack_name}"
    base_prefix = parse_gcs_uri(base_uri)[1].rstrip("/") + "/"
    print(f"[pull] {base_uri} → {dest_dir}", file=sys.stderr)

    uris = list_files(base_uri)
    if not uris:
        print(f"no files found at {base_uri}", file=sys.stderr)
        return 1

    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for uri in uris:
        _, blob_path = parse_gcs_uri(uri)
        rel = blob_path[len(base_prefix):] if blob_path.startswith(base_prefix) else Path(blob_path).name
        local_path = dest_dir / rel
        download_file(uri, local_path)
        count += 1
        print(f"  {rel}", file=sys.stderr)

    print(f"[OK] downloaded {count} files to {dest_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
