#!/usr/bin/env python3
"""Strong static validation for timeline JSONs.

Runs ahead of (or instead of) the pipeline's built-in validator. Catches
issues that would otherwise cost a real pipeline run:

- Asset paths in `reference_images` / `reference_audios` / `reference_videos`
  must exist on disk (or be {"ref": "..."} pointing at another clip in the
  same timeline).
- Mutual exclusions on Seedance:
    * `first_frame` and `reference_images` are mutually exclusive
    * `reference_audios` requires at least one `reference_images` or
      `reference_videos`
- Duration bounds: integer 4-15 (Seedance) or -1 for auto.
- Words-per-second sanity: count the words spoken in single-quoted lines
  inside the prompt, divide by 2.5; flag if larger than the duration
  (you've written more dialogue than fits).
- Moderation pattern flags (warnings, not errors): named studios
  ("Studio Ghibli", "Pixar", "Robot Chicken"), photoreal markers
  ("photorealistic", "live action"), and a small list of high-recognition
  political figures known to trip Seedance copyright filter.

Usage:
    python scripts/timeline_validate.py <timeline.json>
    python scripts/timeline_validate.py <timeline.json> --strict   # warnings -> errors
    python scripts/timeline_validate.py <timeline.json> --json     # machine output
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


# Patterns that have triggered Seedance moderation in this codebase. Heuristic.
NAMED_STUDIO_PATTERNS = [
    r"\bStudio Ghibli\b", r"\bPixar\b", r"\bDisney\b", r"\bRobot Chicken\b",
    r"\bAardman\b", r"\bLaika\b", r"\bMAPPA\b", r"\bStudio Trigger\b",
    r"\bGhibli\b",
]
PHOTOREAL_MARKERS = [
    r"\bphotoreal", r"\bphoto-real", r"\blive action\b", r"\blive-action\b",
    r"\bcinematic photo\b", r"\b8k photo\b",
]
POLITICAL_LIKENESS_FLAGS = [
    r"\bTrump\b", r"\bBiden\b", r"\bObama\b", r"\bPutin\b", r"\bXi Jinping\b",
    r"\bZelensky\b", r"\bNetanyahu\b",
]


def _is_ref_obj(x: Any) -> bool:
    return isinstance(x, dict) and "ref" in x


def _find_quoted_dialogue(prompt: str) -> List[str]:
    """Extract single-quoted spans from a prompt — heuristic for dialogue."""
    # Match 'text' but not contractions like don't, FAQ-9000's
    # Use a min-3-words filter to avoid pulling in possessives
    matches = re.findall(r"'([^']{15,})'", prompt)
    return [m for m in matches if len(m.split()) >= 3]


def _word_count(text: str) -> int:
    return len(re.split(r"\s+", text.strip())) if text.strip() else 0


def _flag_patterns(text: str, patterns: List[str]) -> List[str]:
    hits = []
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            hits.append(m.group(0))
    return hits


def validate(timeline_path: Path, project_root: Path) -> Tuple[List[Dict], List[Dict]]:
    """Returns (errors, warnings) as lists of {clip_id, level, code, message}."""
    timeline = json.loads(timeline_path.read_text())
    errors: List[Dict] = []
    warnings: List[Dict] = []

    # Collect all clip IDs across all tracks for ref resolution
    all_clip_ids: set = set()
    for track in timeline.get("tracks", []):
        for clip in track.get("clips", []):
            cid = clip.get("id")
            if cid:
                all_clip_ids.add(cid)

    for track in timeline.get("tracks", []):
        for clip in track.get("clips", []):
            cid = clip.get("id", "<unknown>")
            source = clip.get("source", {})
            if source.get("type") != "video":
                continue

            ref_images = source.get("reference_images", [])
            ref_audios = source.get("reference_audios", [])
            ref_videos = source.get("reference_videos", [])
            first_frame = source.get("first_frame")
            duration = clip.get("duration") or source.get("duration") or \
                       timeline.get("defaults", {}).get("video", {}).get("duration", 5)
            prompt = source.get("prompt", "")

            # Mutual exclusion: first_frame + reference_images
            if first_frame and ref_images:
                errors.append({
                    "clip_id": cid, "level": "error", "code": "FF_AND_REFIMG",
                    "message": "first_frame and reference_images are mutually exclusive on Seedance",
                })

            # reference_audios requires reference_images or reference_videos
            if ref_audios and not ref_images and not ref_videos:
                errors.append({
                    "clip_id": cid, "level": "error", "code": "AUDIO_NEEDS_IMAGE",
                    "message": "reference_audios requires at least one reference_images or reference_videos entry (Seedance E006)",
                })

            # Duration bounds
            if duration not in (-1,) and not isinstance(duration, int):
                warnings.append({
                    "clip_id": cid, "level": "warn", "code": "DURATION_NOT_INT",
                    "message": f"duration must be int 4-15 or -1 for Seedance (got {duration!r})",
                })
            elif isinstance(duration, int) and duration != -1 and not (4 <= duration <= 15):
                errors.append({
                    "clip_id": cid, "level": "error", "code": "DURATION_OUT_OF_BOUNDS",
                    "message": f"duration must be 4-15 (got {duration}) — Seedance rejects with E006",
                })

            # Verify reference asset paths exist (for string entries)
            for label, lst in (("reference_images", ref_images),
                               ("reference_audios", ref_audios),
                               ("reference_videos", ref_videos)):
                for entry in lst:
                    if isinstance(entry, str):
                        if entry.startswith(("http://", "https://", "gs://")):
                            continue
                        path = (project_root / entry) if not Path(entry).is_absolute() else Path(entry)
                        if not path.exists():
                            errors.append({
                                "clip_id": cid, "level": "error", "code": "MISSING_ASSET",
                                "message": f"{label} entry not found on disk: {entry}",
                            })
                    elif _is_ref_obj(entry):
                        ref_id = entry.get("ref")
                        if ref_id and ref_id not in all_clip_ids:
                            errors.append({
                                "clip_id": cid, "level": "error", "code": "BAD_REF",
                                "message": f"{label} ref points at unknown clip id: {ref_id!r}",
                            })

            # WPS sanity check on dialogue inside the prompt
            dialogue_words = sum(_word_count(line) for line in _find_quoted_dialogue(prompt))
            if dialogue_words > 0 and isinstance(duration, int) and duration > 0:
                expected = dialogue_words / 2.5
                if expected > duration + 1.0:
                    warnings.append({
                        "clip_id": cid, "level": "warn", "code": "TOO_MUCH_DIALOGUE",
                        "message": (
                            f"~{dialogue_words} words of dialogue at WPS 2.5 = {expected:.1f}s, "
                            f"but clip duration is {duration}s — line will be rushed or cut off"
                        ),
                    })

            # Moderation pattern flags (warnings)
            for hits, code, msg in (
                (_flag_patterns(prompt, NAMED_STUDIO_PATTERNS), "NAMED_STUDIO",
                 "named studio in prompt — Seedance may flag as copyright"),
                (_flag_patterns(prompt, PHOTOREAL_MARKERS), "PHOTOREAL_MARKER",
                 "photoreal marker in prompt — refs that read as photographs trigger E005"),
                (_flag_patterns(prompt, POLITICAL_LIKENESS_FLAGS), "POLITICAL_LIKENESS",
                 "named political figure — if rendered as a recognizable face in any ref, Seedance will block"),
            ):
                if hits:
                    warnings.append({
                        "clip_id": cid, "level": "warn", "code": code,
                        "message": f"{msg} (matched: {hits[0]!r})",
                    })

    return errors, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a timeline JSON before running the pipeline")
    ap.add_argument("timeline", help="Path to timeline.json")
    ap.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    ap.add_argument("--json", dest="json_out", action="store_true", help="Machine-readable JSON output")
    args = ap.parse_args()

    p = Path(args.timeline).resolve()
    if not p.is_file():
        print(f"not a file: {p}", file=sys.stderr)
        return 2

    # Reference paths in timelines are interpreted relative to the project root
    # (the CWD when pipeline.py is invoked), not the timeline file's directory.
    project_root = Path(__file__).resolve().parent.parent
    errors, warnings = validate(p, project_root)

    if args.json_out:
        print(json.dumps({"errors": errors, "warnings": warnings}, indent=2))
    else:
        for w in warnings:
            print(f"⚠ {w['clip_id']}  {w['code']}: {w['message']}")
        for e in errors:
            print(f"✖ {e['clip_id']}  {e['code']}: {e['message']}")
        n_e, n_w = len(errors), len(warnings)
        if n_e == 0 and n_w == 0:
            print(f"✓ {p.name}: clean")
        else:
            print(f"\n{n_e} error(s), {n_w} warning(s)")

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
