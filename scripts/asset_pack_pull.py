#!/usr/bin/env python3
"""Download a named pack from R2 to a local directory.

Mirror of asset_pack_push.py. Pulls everything under
r2://$R2_BUCKET_NAME/<prefix>/<pack_name>/ to <dest_dir>/<pack_name>/,
preserving the relative directory structure.

Default prefix is `asset-packs`. Use `--prefix style-packs` for style packs.

Usage:
    python scripts/asset_pack_pull.py <pack_name> [<dest_dir>] [--prefix <prefix>]

Examples:
    # Asset pack (default prefix)
    python scripts/asset_pack_pull.py news-show-v1
    # → runs/asset-packs/news-show-v1/

    # Style pack
    python scripts/asset_pack_pull.py ig-DW2FRgojpMa --prefix style-packs
    # → runs/style-packs/ig-DW2FRgojpMa/
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cloudrun.r2_storage import download_file, list_files, parse_uri


def _resolve_bucket() -> str:
    name = os.environ.get("R2_BUCKET_NAME") or os.environ.get("R2_BUCKET")
    if name:
        return name.strip().strip("/")
    legacy = os.environ.get("GCS_OUTPUT_BUCKET", "").strip()
    if legacy:
        for scheme in ("gs://", "r2://", "s3://"):
            if legacy.startswith(scheme):
                legacy = legacy[len(scheme):]
                break
        return legacy.split("/", 1)[0].strip("/")
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Download a named pack from R2")
    ap.add_argument("pack_name", help="Pack name to pull")
    ap.add_argument(
        "dest_dir",
        nargs="?",
        default=None,
        help="Destination root directory (default: runs/<prefix>/)",
    )
    ap.add_argument(
        "--prefix",
        default="asset-packs",
        help="R2 path component (default: asset-packs). Use 'style-packs' for style-rip packs.",
    )
    args = ap.parse_args()

    pack_name = args.pack_name
    prefix = args.prefix.strip("/")
    dest_root = (
        Path(args.dest_dir).resolve()
        if args.dest_dir
        else (Path(__file__).resolve().parent.parent / "runs" / prefix)
    )
    dest_dir = dest_root / pack_name

    bucket = _resolve_bucket()
    if not bucket:
        print("R2_BUCKET_NAME not set", file=sys.stderr)
        return 2

    base_uri = f"r2://{bucket}/{prefix}/{pack_name}"
    base_prefix = parse_uri(base_uri)[1].rstrip("/") + "/"
    print(f"[pull] {base_uri} → {dest_dir}", file=sys.stderr)

    uris = list_files(base_uri)
    if not uris:
        print(f"no files found at {base_uri}", file=sys.stderr)
        return 1

    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for uri in uris:
        _, key = parse_uri(uri)
        rel = key[len(base_prefix):] if key.startswith(base_prefix) else Path(key).name
        local_path = dest_dir / rel
        download_file(uri, local_path)
        count += 1
        print(f"  {rel}", file=sys.stderr)

    print(f"[OK] downloaded {count} files to {dest_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
