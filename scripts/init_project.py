#!/usr/bin/env python3
"""Scaffold a new project directory.

Creates runs/<slug>/ with three files:
- <slug>.json         — starter timeline (one clip, points at the ref the manifest produces)
- refs-manifest.json  — starter batch_image_gen.py manifest (one example request)
- CLAUDE.md           — agent-facing next-steps note

The slug is derived from the project name with the same rules scripts/run.py uses,
so the project stays at a stable path across runs.

Usage:
    python scripts/init_project.py "My Project Name"
    python scripts/init_project.py "Kalshi Top 5"   --from-pack news-show-v1
    python scripts/init_project.py "Dating Remix"   --from-pack ig-DXsns8PpVlj

Packs are pulled from the website (https://mograf.ai) via `mograf pack pull`.
The pack's kind (asset vs style) determines where it lands:
  asset → runs/asset-packs/<slug>/
  style → runs/style-packs/<slug>/

After init:
    1. Edit runs/<slug>/refs-manifest.json (add character/scene refs)
    2. python scripts/batch_image_gen.py runs/<slug>/refs-manifest.json
    3. Edit runs/<slug>/<slug>.json (wire generated refs into reference_images)
    4. python scripts/run.py runs/<slug>/<slug>.json
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "project"


def starter_timeline(name: str, slug: str) -> Dict[str, Any]:
    return {
        "version": 1,
        "project": {"name": name},
        "defaults": {
            "video": {
                "model": "seedance-2.0-fast",
                "duration": 6,
            },
        },
        "tracks": [
            {
                "id": "visuals",
                "type": "video",
                "clips": [
                    {
                        "id": "vid-1",
                        "source": {
                            "type": "video",
                            "prompt": "TODO: describe the video clip",
                            "reference_images": [
                                f"runs/{slug}/refs/character.png"
                            ],
                        },
                    }
                ],
            }
        ],
    }


def starter_manifest(slug: str) -> Dict[str, Any]:
    return {
        "concurrency": 5,
        "requests": [
            {
                "id": "character-ref",
                "model": "gpt-image-2",
                "prompt": "TODO: describe the character/scene reference image",
                "output_path": f"runs/{slug}/refs/character.png",
                "aspect_ratio": "16:9",
                "output_format": "png",
                "quality": "high",
            }
        ],
    }


CLAUDE_MD_TEMPLATE = """# {name}

Project scratch dir. Workflow:

1. Edit `refs-manifest.json` — add character/scene reference image requests. See `scripts/batch_image_gen.py` for the full manifest schema (`gpt-image-2` and `nano-banana-2` models supported).
2. Generate refs:
   ```bash
   python scripts/batch_image_gen.py runs/{slug}/refs-manifest.json
   ```
3. Edit `{slug}.json` — wire the generated ref paths into clips' `reference_images`. See the patterns in the repo-root `README.md` for shapes (chained sequences, narrated explainer, etc.).
4. Run the pipeline:
   ```bash
   python scripts/run.py runs/{slug}/{slug}.json
   ```

Output lands in this same dir under `videos/`, `images/`, `final/`. `scripts/run.py` resumes by default, so re-running only re-renders missing/failed clips.
{pack_note}"""


def write_pack_note(pack_slug: str, pack_dir: Path) -> str:
    rel = pack_dir.relative_to(PROJECT_ROOT)
    return (
        "\n## Pack\n\n"
        f"Pulled `{pack_slug}` to `{rel}/`. Use files from there in `reference_images`, "
        "`reference_audios`, or `reference_videos` in your timeline. "
        "Packs live outside the project dir so they can be shared across projects.\n"
    )


def _resolve_pulled_pack_dir(pack_slug: str) -> Path | None:
    """`mograf pack pull` puts the pack in runs/{kind}-packs/<slug>/. We don't
    know the kind ahead of time, so look in both expected locations."""
    for prefix in ("asset-packs", "style-packs"):
        candidate = PROJECT_ROOT / "runs" / prefix / pack_slug
        if candidate.is_dir() and any(candidate.iterdir()):
            return candidate
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold a new project directory")
    ap.add_argument("name", help="Project name (will be slugified for the dir)")
    ap.add_argument(
        "--from-pack",
        default=None,
        help="Pull a published pack (asset or style) via `mograf pack pull` before scaffolding.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing scaffold files.",
    )
    args = ap.parse_args()

    slug = slugify(args.name)
    project_dir = PROJECT_ROOT / "runs" / slug

    timeline_path = project_dir / f"{slug}.json"
    manifest_path = project_dir / "refs-manifest.json"
    claude_path = project_dir / "CLAUDE.md"

    if not args.force:
        existing = [p for p in (timeline_path, manifest_path, claude_path) if p.exists()]
        if existing:
            print("Refusing to overwrite existing files:", file=sys.stderr)
            for p in existing:
                print(f"  {p.relative_to(PROJECT_ROOT)}", file=sys.stderr)
            print("Pass --force to overwrite.", file=sys.stderr)
            return 2

    project_dir.mkdir(parents=True, exist_ok=True)

    pack_note = ""
    if args.from_pack:
        print(f"[init] pulling pack '{args.from_pack}' via mograf pack pull")
        rc = subprocess.call(
            [
                sys.executable,
                "-m",
                "mograf.cli",
                "pack",
                "pull",
                args.from_pack,
                "--force",
            ]
        )
        if rc != 0:
            print(
                f"mograf pack pull failed (exit {rc}); aborting init.",
                file=sys.stderr,
            )
            return rc
        pack_dir = _resolve_pulled_pack_dir(args.from_pack)
        if pack_dir is None:
            print(
                f"warning: could not find pulled pack dir for '{args.from_pack}'",
                file=sys.stderr,
            )
        else:
            pack_note = write_pack_note(args.from_pack, pack_dir)

    timeline_path.write_text(json.dumps(starter_timeline(args.name, slug), indent=2) + "\n")
    manifest_path.write_text(json.dumps(starter_manifest(slug), indent=2) + "\n")
    claude_path.write_text(
        CLAUDE_MD_TEMPLATE.format(name=args.name, slug=slug, pack_note=pack_note)
    )

    print(f"[OK] scaffolded {project_dir.relative_to(PROJECT_ROOT)}/")
    print(f"  - {timeline_path.relative_to(PROJECT_ROOT)}")
    print(f"  - {manifest_path.relative_to(PROJECT_ROOT)}")
    print(f"  - {claude_path.relative_to(PROJECT_ROOT)}")
    print()
    print("Next: edit refs-manifest.json, then:")
    print(f"  python scripts/batch_image_gen.py runs/{slug}/refs-manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
