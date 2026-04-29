#!/usr/bin/env python3
"""Key a chroma-green character video to a transparent VP8-alpha webm.

Usage:
    python scripts/key_character.py <input.mp4> --out <output.webm> [--poster <poster.png>]

Pipeline:
1. Decode every frame as PNG.
2. Compute alpha via PIL green-excess (g - max(r,b)) — selective for
   pixels where green is genuinely the dominant channel. Avoids the
   YUV chromakey trap of over-flagging dark hair / shadows.
3. Threshold-snap alpha (>200 → 255, <40 → 0) so the body is fully
   solid and only a 1-2px feathered outline remains.
4. Despill green by pulling the green channel toward (r+b)/2 wherever
   green excess > 0.
5. Bbox-scan all frames; crop to the union + 50px padding.
6. Re-encode with libvpx (VP8) at yuva420p — VP9 alpha is dropped by
   some ffmpeg builds.

See `docs/character-asset/README.md` for the full workflow.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


# Tunables --------------------------------------------------------------
# Green-excess ramp: pixels with green_excess <= LO are fully transparent,
# pixels with green_excess >= HI are fully opaque, linear ramp in between.
GE_LO = 10.0
GE_HI = 40.0

# Alpha threshold-snap: hardens the matte after the ramp.
ALPHA_OPAQUE = 200
ALPHA_CLEAR = 40

# Despill mix: how aggressively to pull green toward (r+b)/2 on edge pixels.
DESPILL_MIX = 0.9

# Crop padding around the union bbox (pixels).
PAD = 50

# Encoder bitrate target.
BITRATE = "2000k"

# Output framerate (matches Seedance default of 24fps).
FPS = 24


def key_frame(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (despilled_rgb, hardened_alpha) for one frame as float32 array."""
    arr = rgb.astype(np.float32)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    green_excess = g - np.maximum(r, b)

    # Soft matte from green excess
    alpha = np.clip((GE_HI - green_excess) / (GE_HI - GE_LO), 0.0, 1.0) * 255.0

    # Threshold-snap
    alpha = np.where(alpha > ALPHA_OPAQUE, 255.0, alpha)
    alpha = np.where(alpha < ALPHA_CLEAR, 0.0, alpha)

    # Despill: pull green channel toward neutral (avg of red+blue) where green dominates
    spill = np.clip(green_excess, 0, 50) / 50.0
    target_g = (r + b) / 2.0
    arr[..., 1] = g * (1 - spill * DESPILL_MIX) + target_g * (spill * DESPILL_MIX)

    return arr, alpha


def find_union_bbox(frame_paths: list[Path]) -> tuple[int, int, int, int]:
    """Return (min_x, max_x, min_y, max_y) across all frames after keying."""
    min_x, max_x = 1 << 30, 0
    min_y, max_y = 1 << 30, 0
    for fp in frame_paths:
        rgb = np.asarray(Image.open(fp).convert("RGB"))
        _, alpha = key_frame(rgb)
        mask = alpha >= ALPHA_OPAQUE
        if not mask.any():
            continue
        rows = np.any(mask, axis=1)
        cols = np.any(mask, axis=0)
        ys = np.where(rows)[0]
        xs = np.where(cols)[0]
        min_x = min(min_x, int(xs[0]))
        max_x = max(max_x, int(xs[-1]))
        min_y = min(min_y, int(ys[0]))
        max_y = max(max_y, int(ys[-1]))
    return min_x, max_x, min_y, max_y


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Key a chroma-green character video to a transparent VP8-alpha webm."
    )
    ap.add_argument("input", type=Path, help="Input mp4 (chroma-green background)")
    ap.add_argument("--out", type=Path, required=True, help="Output webm path")
    ap.add_argument("--poster", type=Path, default=None, help="Optional poster PNG path (mid-frame)")
    ap.add_argument("--pad", type=int, default=PAD, help=f"Crop padding (default {PAD}px)")
    ap.add_argument("--bitrate", default=BITRATE, help=f"VP8 bitrate (default {BITRATE})")
    ap.add_argument("--fps", type=int, default=FPS, help=f"Output FPS (default {FPS})")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.poster:
        args.poster.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="key_char_") as tmp:
        tmp = Path(tmp)
        raw_dir = tmp / "raw"
        keyed_dir = tmp / "keyed"
        raw_dir.mkdir()
        keyed_dir.mkdir()

        print(f"decoding frames from {args.input.name}…")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(args.input),
             str(raw_dir / "%04d.png")],
            check=True,
        )
        frames = sorted(raw_dir.iterdir())
        if not frames:
            print("ffmpeg produced no frames", file=sys.stderr)
            return 2
        first = Image.open(frames[0])
        src_w, src_h = first.size

        print(f"scanning {len(frames)} frames for character bbox…")
        min_x, max_x, min_y, max_y = find_union_bbox(frames)
        print(f"  bbox: x={min_x}-{max_x} ({max_x - min_x} wide), "
              f"y={min_y}-{max_y} ({max_y - min_y} tall)")

        cx = max(0, min_x - args.pad)
        cw = min(src_w, max_x + args.pad) - cx
        cw = (cw + 1) // 2 * 2  # even
        cy = max(0, min_y - args.pad)
        ch = min(src_h, max_y + args.pad) - cy
        ch = ch // 2 * 2
        print(f"  crop: {cw}x{ch} at ({cx},{cy})")

        mid = len(frames) // 2
        print("keying + cropping each frame…")
        for i, fp in enumerate(frames):
            rgb = np.asarray(Image.open(fp).convert("RGB"))
            arr, alpha = key_frame(rgb)
            rgba = np.dstack([arr, alpha]).astype(np.uint8)
            cropped = rgba[cy:cy + ch, cx:cx + cw]
            Image.fromarray(cropped).save(keyed_dir / fp.name)
            if i == mid and args.poster:
                Image.fromarray(cropped).save(args.poster)
            if i % 60 == 0:
                print(f"  {i}/{len(frames)}")

        print(f"encoding VP8-alpha webm to {args.out.name}…")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-framerate", str(args.fps), "-i", str(keyed_dir / "%04d.png"),
             "-c:v", "libvpx", "-pix_fmt", "yuva420p",
             "-auto-alt-ref", "0", "-b:v", args.bitrate, "-an",
             str(args.out)],
            check=True,
        )

    size_mb = args.out.stat().st_size / 1024 / 1024
    print(f"done: {args.out} ({size_mb:.1f} MB at {cw}x{ch})")
    if args.poster:
        print(f"      {args.poster}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
