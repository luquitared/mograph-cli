"""
Assemble a mograph music-video timeline run into a final mp4.

The mograph pipeline's `final` stage currently does not trim per float
`clip.duration`, nor mux `file`-source audio tracks on music-video timelines
(where there's no `narration` track). This script does both: for each clip in
the timeline's video track, it trims the generated mp4 to `clip.duration` and
concatenates; then muxes with the audio track's file source.

Usage:
    python assemble_music_video.py <timeline.json> <run_dir> <output.mp4> \\
        [--extra-videos-dir DIR ...]

`--extra-videos-dir` flags let you fold in retry runs. Later dirs win,
so put retries last.

Example:
    python assemble_music_video.py \\
        liquidated-music-video.json \\
        runs/Liquidated_Full_Music_Video-20260418-162653 \\
        liquidated_full_music_video.mp4 \\
        --extra-videos-dir runs/Liquidated_Retry-20260418-163438/videos \\
        --extra-videos-dir runs/Liquidated_Retry_2-20260418-163659/videos
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def find_clip_file(clip_id: str, video_dirs: list[Path]) -> Path:
    for d in reversed(video_dirs):
        candidate = d / f"{clip_id}.mp4"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Cannot find {clip_id}.mp4 in any of: {video_dirs}")


def trim(src: Path, dur: float, dst: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(src),
        "-t", f"{dur}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", "30", "-an",
        str(dst),
    ], check=True)


def concat(parts: list[Path], dst: Path, tmp: Path) -> None:
    listfile = tmp / "list.txt"
    listfile.write_text("\n".join(f"file '{p}'" for p in parts) + "\n")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(listfile),
        "-c", "copy",
        str(dst),
    ], check=True)


def mux(video: Path, audio: Path, dst: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video),
        "-i", str(audio),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(dst),
    ], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("timeline", help="Path to the mograph timeline JSON")
    ap.add_argument("run_dir", help="Run directory (e.g. runs/My_Project-20260418-120000)")
    ap.add_argument("output", help="Output mp4 path")
    ap.add_argument("--extra-videos-dir", action="append", default=[],
                    help="Extra videos directories to pull retry clips from. Later flags win.")
    args = ap.parse_args()

    timeline_path = Path(args.timeline)
    tl = json.loads(timeline_path.read_text())

    video_dirs = [Path(args.run_dir) / "videos"]
    for extra in args.extra_videos_dir:
        video_dirs.append(Path(extra))

    video_clips: list[tuple[str, float]] = []
    audio_path: Path | None = None

    for track in tl["tracks"]:
        if track["type"] == "video":
            for c in track["clips"]:
                dur = c.get("duration")
                if dur is None or dur == "auto":
                    dur = c["source"].get("duration", 5)
                video_clips.append((c["id"], float(dur)))
        elif track["type"] == "audio" and audio_path is None:
            for c in track["clips"]:
                src = c["source"]
                if src.get("type") == "file":
                    p = Path(src["path"])
                    if not p.is_absolute():
                        p = timeline_path.parent / p
                    audio_path = p
                    break

    if not video_clips:
        print("no video clips found in timeline", file=sys.stderr)
        return 2
    if audio_path is None:
        print("no file-source audio track found in timeline", file=sys.stderr)
        return 2
    if not audio_path.exists():
        print(f"audio file not found: {audio_path}", file=sys.stderr)
        return 2

    total_dur = sum(d for _, d in video_clips)
    print(f"[assemble] {len(video_clips)} clips, {total_dur:.2f}s total, audio={audio_path}")

    with tempfile.TemporaryDirectory(prefix="mograph_assemble_") as td:
        tmp = Path(td)
        trimmed: list[Path] = []
        for clip_id, dur in video_clips:
            src = find_clip_file(clip_id, video_dirs)
            dst = tmp / f"{clip_id}.mp4"
            trim(src, dur, dst)
            trimmed.append(dst)
            print(f"  {clip_id:<25} {dur:5.2f}s  <- {src}")

        visuals = tmp / "visuals.mp4"
        concat(trimmed, visuals, tmp)
        mux(visuals, audio_path, Path(args.output))

    probe = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        args.output,
    ]).decode().strip()
    print(f"[done] {args.output}  duration={probe}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
