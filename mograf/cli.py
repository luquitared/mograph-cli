#!/usr/bin/env python3
"""mograf — push and share AI video workflows.

Subcommands:
    login                          — link this machine via GitHub device flow
    workflow new SLUG              — scaffold a new workflow folder
    workflow push [DIR]            — publish a workflow folder
    workflow pull SLUG             — download a workflow into ./<slug>/
    workflow run SLUG              — pull + run pipeline.py on the main timeline
    workflow list                  — list workflows you've pushed
    workflow rm SLUG               — delete one of your workflows
    workflow open SLUG             — open a workflow page in your browser
    publish RUN_DIR                — turn a pipeline run dir into a workflow

Config: ~/.config/mograf/credentials.json (override with MOGRAF_HOME env)
API:    https://mograf.ai (override with MOGRAF_API env)

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
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Optional

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEFAULT_API = os.environ.get(
    "MOGRAF_API", os.environ.get("MOGRAPH_API", "https://mograph.lucasnegritto7538.workers.dev")
)
CONFIG_DIR = Path(
    os.environ.get("MOGRAF_HOME", os.environ.get("MOGRAPH_HOME", str(Path.home() / ".config" / "mograf")))
)
CREDS_FILE = CONFIG_DIR / "credentials.json"

# Best-effort: load .env from the repo root so GITHUB_CLIENT_ID etc. are
# available without the user having to export them manually.
def _load_dotenv() -> None:
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for env_path in candidates:
        if not env_path.is_file():
            continue
        try:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            pass


_load_dotenv()

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


def _github_device_flow(client_id: str) -> str:
    """Run the GitHub OAuth device flow. Returns an access token."""
    dev = requests.post(
        "https://github.com/login/device/code",
        data={"client_id": client_id, "scope": "read:user user:email"},
        headers={"Accept": "application/json"},
        timeout=20,
    )
    if not dev.ok:
        sys.exit(f"github device/code failed: {dev.status_code} {dev.text}")
    dev_data = dev.json()
    if "error" in dev_data:
        sys.exit(
            f"github error: {dev_data.get('error')} — {dev_data.get('error_description', '')}"
        )
    device_code = dev_data["device_code"]
    user_code = dev_data["user_code"]
    verify_uri = (
        dev_data.get("verification_uri_complete") or dev_data["verification_uri"]
    )
    interval = max(int(dev_data.get("interval", 5)), 2)
    expires_in = int(dev_data.get("expires_in", 900))

    print(f"\n  Open this URL in a browser:\n    {verify_uri}\n")
    print(f"  Enter this code:  {user_code}\n")
    print(f"  Code expires in {expires_in // 60} minutes.")

    try:
        webbrowser.open(verify_uri)
    except Exception:
        pass

    print("\n  Waiting for authorization (Ctrl-C to stop)…")
    deadline = time.time() + expires_in
    while time.time() < deadline:
        try:
            tok = requests.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
                timeout=20,
            )
            payload = tok.json()
        except requests.RequestException:
            time.sleep(interval)
            continue

        err = payload.get("error")
        if err == "authorization_pending":
            time.sleep(interval)
            continue
        if err == "slow_down":
            interval += 5
            time.sleep(interval)
            continue
        if err in ("expired_token", "access_denied"):
            sys.exit(f"\n✗ {err}: {payload.get('error_description', '')}")
        if err:
            sys.exit(
                f"\n✗ github error: {err} {payload.get('error_description', '')}"
            )
        if payload.get("access_token"):
            return payload["access_token"]
        time.sleep(interval)
    sys.exit("\n✗ Timed out before authorization.")


def _device_label() -> str:
    """A short, human-readable label for this machine — shown on /settings."""
    try:
        import platform as _platform
        node = _platform.node() or "unknown"
        sysname = _platform.system()
        return f"{node} ({sysname})"
    except Exception:
        return "cli"


def cmd_login(args, creds):
    if creds and not args.force:
        print(f"Already linked as @{creds.get('handle', '?')}")
        if creds.get("github_login"):
            print(f"  github: @{creds['github_login']}")
        print(f"  config: {CREDS_FILE}")
        print("\n  --force re-runs the device flow and rotates the keypair.")
        return

    client_id = (
        args.client_id
        or os.environ.get("MOGRAF_GITHUB_CLIENT_ID")
        or os.environ.get("GITHUB_CLIENT_ID")
    )
    if not client_id:
        sys.exit(
            "GITHUB_CLIENT_ID is not set. Add it to .env or pass --client-id.\n"
            "(Public OAuth client id — the secret stays on the server.)"
        )

    print(f"Linking this machine to mograf ({args.api})")
    access_token = _github_device_flow(client_id)

    # Generate a fresh keypair for this device.
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
    privkey_b64 = b64std(priv_bytes)

    # Stage creds so sign_request can use them.
    body_obj = {
        "github_access_token": access_token,
        "label": args.label or _device_label(),
    }
    body = json.dumps(body_obj).encode()
    headers = sign_request(privkey_b64, "POST", "/api/cli/register", body)
    headers["content-type"] = "application/json"

    resp = requests.post(
        f"{args.api}/api/cli/register",
        data=body,
        headers=headers,
        timeout=30,
    )
    if not resp.ok:
        sys.exit(f"\n✗ register failed: {resp.status_code} {resp.text}")
    info = resp.json()
    user = info.get("user", {})

    save_creds(
        {
            "api_base": args.api,
            "pubkey": pubkey_b64,
            "privkey": privkey_b64,
            "handle": user.get("handle", ""),
            "user_id": user.get("id", ""),
            "github_login": user.get("github_login"),
            "display_name": user.get("display_name"),
        }
    )
    print(
        f"\n✓ Linked as @{user.get('handle', '?')}"
        + (f" (github.com/{user['github_login']})" if user.get("github_login") else "")
    )
    print(f"  Keypair stored at {CREDS_FILE}")
    print("  Treat this file like an SSH private key.")


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


def _extract_timeline_metadata(files: list) -> dict:
    """Walk staged timeline JSON files and aggregate models / clip count / duration."""
    models: set[str] = set()
    clip_count = 0
    durations_per_track: list[float] = []

    timeline_paths = [p for p, k, _ in files if k == "timeline"]
    if not timeline_paths:
        return {}

    for p in timeline_paths:
        try:
            doc = json.loads(p.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        defaults = doc.get("defaults") if isinstance(doc.get("defaults"), dict) else {}
        default_dur = _coerce_duration(defaults.get("duration"))
        tracks = doc.get("tracks") if isinstance(doc.get("tracks"), list) else []
        track_total_max = 0.0
        for track in tracks:
            if not isinstance(track, dict):
                continue
            clips = track.get("clips") if isinstance(track.get("clips"), list) else []
            track_dur = 0.0
            for clip in clips:
                if not isinstance(clip, dict):
                    continue
                clip_count += 1
                model = clip.get("model")
                if isinstance(model, str) and model.strip():
                    models.add(model.strip())
                d = _coerce_duration(clip.get("duration") or clip.get("duration_s"))
                if d is None:
                    d = default_dur
                if d is not None:
                    track_dur += d
            track_total_max = max(track_total_max, track_dur)
        durations_per_track.append(track_total_max)

    out: dict = {}
    if models:
        out["models"] = sorted(models)
    if clip_count:
        out["clip_count"] = clip_count
    if durations_per_track:
        total = max(durations_per_track)
        if total > 0:
            out["total_duration_s"] = int(round(total))
    return out


def _coerce_duration(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v >= 0 else None
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def cmd_push(args, creds):
    if not creds:
        sys.exit("Not logged in. Run: mograf login")
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
    for p, k, rel in files:
        data = p.read_bytes()
        is_main = (
            k == "video"
            and (rel == main_name or os.path.basename(rel) == main_name)
        )
        entry = {
            "name": os.path.basename(rel),
            "path": rel.replace(os.sep, "/"),
            "kind": k,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if is_main:
            entry["is_main_video"] = True
        manifest.append(entry)

    metadata = _extract_timeline_metadata(files)
    body_obj = {
        "title": title,
        "summary": summary,
        "readme_md": readme,
        "files": manifest,
    }
    if metadata:
        body_obj["metadata"] = metadata
    update_slug = getattr(args, "update", None)
    if update_slug:
        body_obj["slug"] = update_slug
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

    file_by_path = {rel.replace(os.sep, "/"): p for p, _, rel in files}
    for u in info["uploads"]:
        local = file_by_path.get(u["path"])
        if not local:
            print(f"warn: no local file for {u['path']}", file=sys.stderr)
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
        sys.exit("Not logged in. Run: mograf login")
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
        sys.exit("Not logged in. Run: mograf login")
    url = f"{creds['api_base']}/workflows/{args.slug}"
    print(url)
    webbrowser.open(url)


def cmd_workflow_new(args, _creds):
    target = Path(args.dir).resolve() if args.dir else (
        Path.cwd() / "docs" / "workflows" / args.slug
    )
    if target.exists() and any(target.iterdir()):
        if not args.force:
            sys.exit(
                f"{target} already exists and is non-empty. Use --force to overwrite."
            )
    (target / "examples").mkdir(parents=True, exist_ok=True)
    (target / "videos").mkdir(parents=True, exist_ok=True)
    readme_path = target / "README.md"
    if not readme_path.exists() or args.force:
        readme_path.write_text(_readme_template(args.slug, args.title))
    print(f"✓ Scaffolded {target}")
    print(f"  edit  {readme_path}")
    print(f"  add   examples/<your-timeline>.json")
    print(f"  add   videos/<rendered>.mp4   (or place under examples/)")
    print(f"  push  mograf workflow push {target}")


def _readme_template(slug: str, title: Optional[str]) -> str:
    pretty = title or slug.replace("-", " ").replace("_", " ").title()
    return (
        f"# {pretty}\n"
        "\n"
        "One-line summary of what this workflow makes.\n"
        "\n"
        "## Recipe\n"
        "\n"
        "- Model(s) used: (e.g. Seedance 1.1 Pro, Gemini 3.1 Flash TTS)\n"
        "- Duration: \n"
        "- Reference style: \n"
        "\n"
        "## Run it\n"
        "\n"
        "```\n"
        f"python pipeline.py --timeline-file examples/{slug}.json --stage final\n"
        "```\n"
        "\n"
        "## Notes\n"
        "\n"
        "- (any gotchas, multi-clip consistency tips, etc.)\n"
    )


def _read_timeline(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _find_final_video(run_dir: Path) -> Optional[Path]:
    candidates = [
        run_dir / "final" / "final_with_sfx.mp4",
        run_dir / "final" / "final.mp4",
        run_dir / "final_with_sfx.mp4",
        run_dir / "final.mp4",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    # Fallback: any .mp4 under run_dir, prefer one with "final" in the name.
    mp4s = sorted(run_dir.rglob("*.mp4"))
    if not mp4s:
        return None
    mp4s.sort(key=lambda p: (0 if "final" in p.name.lower() else 1, p.stat().st_size * -1))
    return mp4s[0]


def cmd_publish(args, creds):
    if not creds:
        sys.exit("Not logged in. Run: mograf login")
    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        sys.exit(f"Not a directory: {run_dir}")

    final_video = _find_final_video(run_dir)
    if not final_video:
        sys.exit(f"No final mp4 found under {run_dir}")

    timeline_path = run_dir / "timeline.json"
    if not timeline_path.exists():
        candidates = list(run_dir.glob("*.timeline.json")) + list(run_dir.glob("*.json"))
        if candidates:
            timeline_path = candidates[0]
        else:
            timeline_path = None
    timeline = _read_timeline(timeline_path) if timeline_path else None

    project = (timeline or {}).get("project", {})
    title = args.title or project.get("name") or run_dir.name
    summary = args.summary
    if not summary:
        desc = (project.get("description") or "").strip()
        if desc:
            summary = desc.splitlines()[0]

    readme: str
    if args.readme:
        readme = Path(args.readme).read_text()
    else:
        readme = _auto_readme(title, summary, timeline, final_video.name)

    staging = Path(tempfile.mkdtemp(prefix="mograf-publish-"))
    try:
        (staging / "examples").mkdir(parents=True)
        (staging / "README.md").write_text(readme)
        shutil.copy(final_video, staging / "examples" / final_video.name)
        if timeline_path and timeline_path.exists():
            shutil.copy(timeline_path, staging / "examples" / "timeline.json")

        # Re-use cmd_push by faking the namespace it expects.
        push_args = argparse.Namespace(
            path=str(staging),
            main=final_video.name,
            api=creds["api_base"],
            update=getattr(args, "update", None),
        )
        print(f"Publishing run {run_dir.name} as workflow '{title}'…")
        cmd_push(push_args, creds)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _auto_readme(
    title: str,
    summary: Optional[str],
    timeline: Optional[dict],
    main_video_name: str,
) -> str:
    parts: list[str] = [f"# {title}", ""]
    if summary:
        parts.extend([summary, ""])
    parts.append("## Recipe")
    parts.append("")
    if timeline:
        tracks = timeline.get("tracks") or []
        clip_count = sum(len(t.get("clips") or []) for t in tracks)
        models = sorted({
            (c.get("model") or "").strip()
            for t in tracks
            for c in (t.get("clips") or [])
            if c.get("model")
        })
        if models:
            parts.append(f"- Models: {', '.join(models)}")
        if clip_count:
            parts.append(f"- Clips: {clip_count}")
        defaults = timeline.get("defaults") or {}
        if defaults.get("resolution"):
            parts.append(f"- Resolution: {defaults['resolution']}")
        if defaults.get("aspect_ratio"):
            parts.append(f"- Aspect ratio: {defaults['aspect_ratio']}")
    parts.append("")
    parts.append("## Run it")
    parts.append("")
    parts.append("```")
    parts.append("python pipeline.py --timeline-file examples/timeline.json --stage final")
    parts.append("```")
    parts.append("")
    parts.append(f"The rendered output is `examples/{main_video_name}`.")
    parts.append("")
    return "\n".join(parts)


def cmd_rm(args, creds):
    if not creds:
        sys.exit("Not logged in. Run: mograf login")
    api = creds["api_base"]
    slug = args.slug
    if not args.yes:
        confirm = input(f"Permanently delete workflow '{slug}'? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("aborted")
            return
    path = f"/api/workflows/{slug}"
    headers = sign_request(creds["privkey"], "DELETE", path, b"")
    resp = requests.delete(f"{api}{path}", headers=headers, timeout=60)
    if not resp.ok:
        sys.exit(f"delete failed: {resp.status_code} {resp.text}")
    data = resp.json()
    print(f"✓ Deleted {data['slug']} ({data.get('deleted_objects', 0)} R2 objects)")


def _fetch_manifest(api: str, slug: str) -> dict:
    resp = requests.get(f"{api}/api/workflows/{slug}", timeout=20)
    if not resp.ok:
        sys.exit(f"fetch {slug} failed: {resp.status_code} {resp.text}")
    return resp.json()


def _pull_to(target: Path, manifest: dict, api: str, force: bool, quiet: bool = False) -> None:
    if target.exists() and any(target.iterdir()):
        if not force:
            sys.exit(
                f"{target} already exists and is non-empty. Use --force to overwrite."
            )
    target.mkdir(parents=True, exist_ok=True)

    (target / "README.md").write_text(manifest["readme_md"])
    if not quiet:
        print("  ⬇ README.md")

    for f in manifest["files"]:
        rel = f["path"]
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f["url"]
        if url.startswith("/"):
            url = f"{api}{url}"
        with requests.get(url, stream=True, timeout=600) as r:
            if not r.ok:
                sys.exit(f"download {rel} failed: {r.status_code}")
            with open(dest, "wb") as out:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        out.write(chunk)
        if not quiet:
            marker = " ⭐ main" if f.get("is_main") else ""
            print(f"  ⬇ {rel}{marker}")


def cmd_pull(args, creds):
    api = args.api
    slug = args.slug
    target = Path(args.dir).resolve() if args.dir else Path.cwd() / slug
    manifest = _fetch_manifest(api, slug)
    _pull_to(target, manifest, api, args.force)
    print(f"\n✓ Pulled {manifest['title']} @{manifest['handle']}")
    print(f"  → {target}")


def _find_main_timeline(target: Path, manifest: dict) -> Optional[Path]:
    """Pick the timeline JSON that best matches the workflow's main video."""
    timelines = [f for f in manifest["files"] if f["kind"] == "timeline"]
    if not timelines:
        return None
    main_video = next(
        (f for f in manifest["files"] if f["kind"] == "video" and f.get("is_main")),
        None,
    )
    if main_video:
        stem = Path(main_video["name"]).stem
        for t in timelines:
            if Path(t["name"]).stem == stem:
                return target / t["path"]
    # Fall back to a literal `timeline.json` then the first JSON we have.
    named = next((t for t in timelines if Path(t["name"]).name == "timeline.json"), None)
    chosen = named or timelines[0]
    return target / chosen["path"]


def cmd_run(args, _creds):
    api = args.api
    slug = args.slug
    target = Path(args.dir).resolve() if args.dir else Path.cwd() / slug

    manifest = _fetch_manifest(api, slug)
    needs_pull = args.force or (not target.exists()) or not any(target.iterdir())
    if needs_pull:
        print(f"Pulling {slug}…")
        _pull_to(target, manifest, api, force=True)
    else:
        print(f"Reusing {target} (already populated)")

    timeline = _find_main_timeline(target, manifest)
    if not timeline or not timeline.exists():
        sys.exit("Could not locate a timeline JSON to run.")

    repo_root = Path(__file__).resolve().parent.parent
    pipeline = repo_root / "pipeline.py"
    if not pipeline.exists():
        sys.exit(f"pipeline.py not found at {pipeline}")

    cmd = [
        sys.executable,
        str(pipeline),
        "--timeline-file",
        str(timeline),
        "--stage",
        args.stage,
    ]
    if args.mock:
        cmd.append("--mock")
    if args.extra:
        cmd.extend(args.extra)

    print(f"\n→ running: {' '.join(cmd)}\n")
    rc = subprocess.call(cmd, cwd=repo_root)
    sys.exit(rc)


def main():
    ap = argparse.ArgumentParser(
        prog="mograf",
        description="Push and share AI video workflows.",
    )
    ap.add_argument(
        "--api",
        default=DEFAULT_API,
        help=f"API base URL (default: {DEFAULT_API})",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser(
        "login",
        help="Link this machine via GitHub device flow (generates an Ed25519 keypair)",
    )
    p_login.add_argument(
        "--force",
        action="store_true",
        help="Re-run the device flow even if already linked (rotates the keypair)",
    )
    p_login.add_argument(
        "--client-id",
        help="GitHub OAuth client id (defaults to $GITHUB_CLIENT_ID in env)",
    )
    p_login.add_argument(
        "--label",
        help="Human-readable label for this device (defaults to hostname)",
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
    p_push.add_argument(
        "--update",
        metavar="SLUG",
        help="Replace an existing workflow you own (same slug) instead of creating a new one",
    )

    wsub.add_parser("list", help="List your workflows")
    p_open = wsub.add_parser("open", help="Open a workflow in your browser")
    p_open.add_argument("slug")

    p_pull = wsub.add_parser(
        "pull",
        help="Download a workflow into a local directory (no auth needed)",
    )
    p_pull.add_argument("slug", help="Workflow slug (from the URL)")
    p_pull.add_argument("--dir", help="Target directory (defaults to ./<slug>)")
    p_pull.add_argument(
        "--force",
        action="store_true",
        help="Overwrite if target exists and is non-empty",
    )

    p_run = wsub.add_parser(
        "run",
        help="Pull a workflow and run its main timeline through pipeline.py",
    )
    p_run.add_argument("slug", help="Workflow slug (from the URL)")
    p_run.add_argument("--dir", help="Local directory (defaults to ./<slug>)")
    p_run.add_argument(
        "--stage",
        default="final",
        help="Pipeline stage to run (default: final)",
    )
    p_run.add_argument(
        "--mock",
        action="store_true",
        help="Pass --mock to pipeline.py (use local fixtures, no real API calls)",
    )
    p_run.add_argument(
        "--force",
        action="store_true",
        help="Re-pull even if the target directory is already populated",
    )
    p_run.add_argument(
        "--",
        dest="extra",
        nargs=argparse.REMAINDER,
        help="Extra args forwarded to pipeline.py after `--`",
    )

    p_rm = wsub.add_parser("rm", help="Delete one of your published workflows")
    p_rm.add_argument("slug", help="Workflow slug")
    p_rm.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt"
    )

    p_new = wsub.add_parser(
        "new", help="Scaffold a new workflow folder (README + examples/ + videos/)"
    )
    p_new.add_argument("slug", help="Workflow slug (becomes the directory name)")
    p_new.add_argument(
        "--dir",
        help="Target directory (defaults to ./docs/workflows/<slug>)",
    )
    p_new.add_argument("--title", help="Pretty title (defaults to slug)")
    p_new.add_argument(
        "--force",
        action="store_true",
        help="Overwrite README/dirs even if non-empty",
    )

    p_pub = sub.add_parser(
        "publish",
        help="Publish a pipeline run dir as a workflow (auto-detects final mp4 + timeline)",
    )
    p_pub.add_argument(
        "run_dir",
        help="Path to a run directory (e.g. runs/My_Project-20260512-160000)",
    )
    p_pub.add_argument("--title", help="Override the workflow title")
    p_pub.add_argument("--summary", help="One-line summary")
    p_pub.add_argument(
        "--readme",
        help="Path to a custom README.md (defaults to auto-generated from timeline)",
    )
    p_pub.add_argument(
        "--update",
        metavar="SLUG",
        help="Replace an existing workflow you own (same slug)",
    )

    args = ap.parse_args()
    creds = load_creds()

    if args.cmd == "login":
        cmd_login(args, creds)
    elif args.cmd == "publish":
        cmd_publish(args, creds)
    elif args.cmd == "workflow":
        if args.subcmd == "push":
            cmd_push(args, creds)
        elif args.subcmd == "list":
            cmd_list(args, creds)
        elif args.subcmd == "open":
            cmd_open(args, creds)
        elif args.subcmd == "pull":
            cmd_pull(args, creds)
        elif args.subcmd == "rm":
            cmd_rm(args, creds)
        elif args.subcmd == "new":
            cmd_workflow_new(args, creds)
        elif args.subcmd == "run":
            cmd_run(args, creds)


if __name__ == "__main__":
    main()
