#!/usr/bin/env python3
"""mograph — push and share AI video workflows.

Subcommands:
    login                          — generate Ed25519 keypair, claim an anonymous handle
    workflow push [DIR]            — publish a workflow folder
    workflow list                  — list workflows you've pushed
    workflow open SLUG             — open a workflow page in your browser

Config: ~/.config/mograph/credentials.json (override with MOGRAPH_HOME env)
API:    https://mograph.lucasnegritto7538.workers.dev (override with MOGRAPH_API env)

A workflow folder is expected to contain:
    README.md                      — title from first H1, body becomes the readme
    examples/                      — *.json (timeline), *.mp4/.webm/.mov (videos),
                                     *.md / *.txt (extra static files)
    videos/                        — additional *.mp4/.webm/.mov

Exactly one video is marked --main (prompted if more than one).
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEFAULT_API = os.environ.get(
    "MOGRAPH_API", "https://mograph.lucasnegritto7538.workers.dev"
)
CONFIG_DIR = Path(
    os.environ.get("MOGRAPH_HOME", Path.home() / ".config" / "mograph")
)
CREDS_FILE = CONFIG_DIR / "credentials.json"

VIDEO_EXTS = {".mp4", ".webm", ".mov"}


def load_creds() -> Optional[dict]:
    if not CREDS_FILE.exists():
        return None
    try:
        return json.loads(CREDS_FILE.read_text())
    except json.JSONDecodeError:
        sys.exit(f"corrupt credentials at {CREDS_FILE}")


def save_creds(creds: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDS_FILE.write_text(json.dumps(creds, indent=2))
    CREDS_FILE.chmod(0o600)


def b64std(b: bytes) -> str:
    return base64.standard_b64encode(b).decode()


def b64_decode(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    pad = len(s) % 4
    if pad:
        s += "=" * (4 - pad)
    return base64.standard_b64decode(s)


def sign_request(privkey_b64: str, method: str, path: str, body: bytes) -> dict:
    priv = Ed25519PrivateKey.from_private_bytes(b64_decode(privkey_b64))
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    ts = str(int(time.time()))
    digest = hashlib.sha256(body).hexdigest()
    message = f"{method}\n{path}\n{ts}\n{digest}".encode()
    sig = priv.sign(message)
    return {
        "X-Mograph-Pubkey": b64std(pub_bytes),
        "X-Mograph-Timestamp": ts,
        "X-Mograph-Signature": b64std(sig),
    }


def cmd_login(args, creds):
    if creds and not args.force:
        print(f"Already logged in as @{creds['handle']}")
        print(
            "Use --force to regenerate. Note: regenerating drops access to existing pushes."
        )
        return

    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pubkey_b64 = b64std(pub_bytes)

    resp = requests.post(
        f"{args.api}/api/handles",
        json={"pubkey": pubkey_b64},
        timeout=20,
    )
    if not resp.ok:
        sys.exit(f"register failed: {resp.status_code} {resp.text}")
    data = resp.json()

    save_creds(
        {
            "api_base": args.api,
            "pubkey": pubkey_b64,
            "privkey": b64std(priv_bytes),
            "handle": data["handle"],
            "handle_id": data["handle_id"],
        }
    )
    print(f"Logged in as @{data['handle']}")
    print(f"Keypair stored at {CREDS_FILE}")
    print("Treat this file like an SSH private key.")


def parse_workflow_folder(path: Path):
    readme_path = path / "README.md"
    if not readme_path.exists():
        sys.exit(f"No README.md at {readme_path}")
    readme = readme_path.read_text()

    title = path.name
    m = re.search(r"^# +(.+)$", readme, re.M)
    if m:
        title = m.group(1).strip()

    summary: Optional[str] = None
    started = False
    for ln in readme.splitlines():
        if ln.startswith("# "):
            started = True
            continue
        if not started:
            continue
        s = ln.strip()
        if s and not s.startswith("#"):
            summary = s
            break

    files = []  # list of (Path, kind, rel_name)
    for sub in ("examples", "videos"):
        d = path / sub
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext == ".json":
                kind = "timeline"
            elif ext == ".md":
                kind = "md"
            elif ext == ".txt":
                kind = "txt"
            elif ext in VIDEO_EXTS:
                kind = "video"
            else:
                continue
            files.append((p, kind, str(p.relative_to(path))))

    return title, summary, readme, files


def cmd_push(args, creds):
    if not creds:
        sys.exit("Not logged in. Run: mograph login")
    path = Path(args.path).resolve()
    if not path.is_dir():
        sys.exit(f"Not a directory: {path}")

    title, summary, readme, files = parse_workflow_folder(path)
    if not files:
        sys.exit(f"No files to publish in {path} (looked in examples/ and videos/)")

    videos = [(p, k, n) for (p, k, n) in files if k == "video"]
    if not videos:
        sys.exit("Need at least one video (in examples/ or videos/)")

    main_name = args.main
    if main_name:
        if not any(
            n == main_name or os.path.basename(n) == main_name for _, _, n in videos
        ):
            sys.exit(f"--main {main_name} not found among videos")
    elif len(videos) == 1:
        main_name = videos[0][2]
    else:
        print("Multiple videos found:")
        for i, (_, _, n) in enumerate(videos, 1):
            print(f"  {i}. {n}")
        choice = input("Pick the main one [1]: ").strip() or "1"
        idx = int(choice) - 1
        main_name = videos[idx][2]

    print(f"Workflow: {title}")
    print(f"  files: {len(files)} ({len(videos)} videos, main = {main_name})")

    manifest = []
    for p, k, n in files:
        data = p.read_bytes()
        is_main = (
            k == "video"
            and (n == main_name or os.path.basename(n) == main_name)
        )
        entry = {
            "name": os.path.basename(n),
            "kind": k,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if is_main:
            entry["is_main_video"] = True
        manifest.append(entry)

    body_obj = {
        "title": title,
        "summary": summary,
        "readme_md": readme,
        "files": manifest,
    }
    body = json.dumps(body_obj, separators=(",", ":")).encode()

    api = creds["api_base"]
    headers = sign_request(creds["privkey"], "POST", "/api/workflows", body)
    headers["content-type"] = "application/json"

    resp = requests.post(
        f"{api}/api/workflows", data=body, headers=headers, timeout=30
    )
    if not resp.ok:
        sys.exit(f"create failed: {resp.status_code} {resp.text}")
    info = resp.json()

    file_by_name = {os.path.basename(n): p for p, _, n in files}
    for u in info["uploads"]:
        local = file_by_name.get(u["name"])
        if not local:
            print(f"warn: no local file for {u['name']}", file=sys.stderr)
            continue
        ct = "application/octet-stream"
        if u["kind"] == "video":
            ct = "video/mp4"
        elif u["kind"] == "timeline":
            ct = "application/json"
        elif u["kind"] == "md":
            ct = "text/markdown"
        elif u["kind"] == "txt":
            ct = "text/plain"
        print(f"  ⬆ {u['name']} ({local.stat().st_size} bytes)")
        with open(local, "rb") as fh:
            ur = requests.put(
                f"{api}{u['upload_url']}",
                data=fh,
                headers={"content-type": ct},
                timeout=600,
            )
        if not ur.ok:
            sys.exit(f"upload {u['name']} failed: {ur.status_code} {ur.text}")

    fin_path = f"/api/workflows/{info['workflow_id']}/complete"
    fin_headers = sign_request(creds["privkey"], "POST", fin_path, b"")
    fr = requests.post(f"{api}{fin_path}", data=b"", headers=fin_headers, timeout=20)
    if not fr.ok:
        print(f"warn: complete failed: {fr.status_code} {fr.text}", file=sys.stderr)

    print(f"\n✓ Pushed → {api}{info['url']}")


def cmd_list(args, creds):
    if not creds:
        sys.exit("Not logged in. Run: mograph login")
    api = creds["api_base"]
    headers = sign_request(creds["privkey"], "GET", "/api/workflows/mine", b"")
    resp = requests.get(f"{api}/api/workflows/mine", headers=headers, timeout=20)
    if not resp.ok:
        sys.exit(f"list failed: {resp.status_code} {resp.text}")
    data = resp.json()
    rows = data.get("workflows", [])
    if not rows:
        print("No workflows yet.")
        return
    for w in rows:
        title = w["title"]
        print(f"  {w['slug']:<40} {title}")


def cmd_open(args, creds):
    if not creds:
        sys.exit("Not logged in. Run: mograph login")
    url = f"{creds['api_base']}/workflows/{args.slug}"
    print(url)
    webbrowser.open(url)


def main():
    ap = argparse.ArgumentParser(
        prog="mograph",
        description="Push and share AI video workflows.",
    )
    ap.add_argument(
        "--api",
        default=DEFAULT_API,
        help=f"API base URL (default: {DEFAULT_API})",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="Generate keypair, claim a handle")
    p_login.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if logged in (loses access to existing pushes)",
    )

    p_wf = sub.add_parser("workflow", help="Manage workflows")
    wsub = p_wf.add_subparsers(dest="subcmd", required=True)

    p_push = wsub.add_parser("push", help="Publish a workflow folder")
    p_push.add_argument(
        "path",
        help="Path to workflow folder (e.g. docs/workflows/narration-explainer)",
    )
    p_push.add_argument(
        "--main",
        help="Filename of the main video (omit to be prompted)",
    )

    wsub.add_parser("list", help="List your workflows")
    p_open = wsub.add_parser("open", help="Open a workflow in your browser")
    p_open.add_argument("slug")

    args = ap.parse_args()
    creds = load_creds()

    if args.cmd == "login":
        cmd_login(args, creds)
    elif args.cmd == "workflow":
        if args.subcmd == "push":
            cmd_push(args, creds)
        elif args.subcmd == "list":
            cmd_list(args, creds)
        elif args.subcmd == "open":
            cmd_open(args, creds)


if __name__ == "__main__":
    main()
