#!/usr/bin/env python3
"""Audio polish pass for an assembled timeline run.

Takes a pipeline run directory, runs ffmpeg loudnorm on each individual
video clip's audio (EBU R128 -16 LUFS broadcast standard), then re-concats
the normalized clips into a polished final mp4.

Usage:
    python polish_audio.py <run_dir>

    e.g. polish_audio.py runs/Kalshi_Top_5_v2-20260428-120000

Reads:  <run_dir>/videos/*.mp4
Writes: <run_dir>/videos_normalized/*.mp4 and <run_dir>/final/video_polished.mp4
"""

import subprocess
import sys
from pathlib import Path


def loudnorm_clip(src: Path, dst: Path) -> None:
    """Single-pass EBU R128 loudnorm. -16 LUFS, -1.5 dBTP, 11 LU range."""
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-af", "loudnorm=I=-16:LRA=11:tp=-1.5",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        str(dst),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def concat_clips(clip_paths: list[Path], out_path: Path, list_path: Path) -> None:
    """Concat via ffmpeg concat demuxer. Re-encodes audio for safety; copies video."""
    list_path.write_text("\n".join(f"file '{p}'" for p in clip_paths) + "\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: polish_audio.py <run_dir>", file=sys.stderr)
        return 2

    run_dir = Path(sys.argv[1]).resolve()
    if not run_dir.is_dir():
        print(f"not a directory: {run_dir}", file=sys.stderr)
        return 2

    videos_dir = run_dir / "videos"
    if not videos_dir.is_dir():
        print(f"no /videos directory in {run_dir}", file=sys.stderr)
        return 2

    norm_dir = run_dir / "videos_normalized"
    final_dir = run_dir / "final"
    norm_dir.mkdir(exist_ok=True)
    final_dir.mkdir(exist_ok=True)

    clips = sorted(videos_dir.glob("*.mp4"))
    if not clips:
        print(f"no .mp4 files in {videos_dir}", file=sys.stderr)
        return 1

    print(f"[polish] loudnorm on {len(clips)} clips → {norm_dir}", file=sys.stderr)
    normalized: list[Path] = []
    for src in clips:
        dst = norm_dir / src.name
        print(f"  {src.name}", file=sys.stderr)
        loudnorm_clip(src, dst)
        normalized.append(dst)

    out = final_dir / "video_polished.mp4"
    list_path = final_dir / "polish_concat.txt"
    print(f"[polish] concat → {out}", file=sys.stderr)
    concat_clips(normalized, out, list_path)
    print(f"[OK] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
