"""
Render a beat-synced preview video from music_timeline.json.

Each beat (plus transitions, vocal-phrase boundaries, section boundaries)
becomes a colored card with overlay text (section label / lyric /
visual_prompt). Audio is the 30s clip muxed in at the end.

PIL is used to pre-render each card as a PNG because this ffmpeg build has
no drawtext filter.

Usage:
    python render_music_cuts.py music_timeline.json liquidated_30s.mp3 music_cuts.mp4
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 30
MIN_SEG = 0.18  # seconds — drop cuts closer than this to the previous
FONT_BLACK = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"

PALETTES = {
    "intro":        ["#0a0e2a", "#1a1340", "#241539", "#0f1a3d"],
    "instrumental": ["#ff1b8d", "#00e5ff", "#b300ff", "#ff4d00", "#00ff88"],
    "verse":        ["#d63031", "#ff6348", "#fdcb6e", "#00b894", "#0984e3", "#e84393"],
    "chorus":       ["#ff006e", "#fb5607", "#ffbe0b", "#8338ec", "#3a86ff"],
    "bridge":       ["#6c5ce7", "#a29bfe", "#fd79a8"],
    "outro":        ["#2d3436", "#636e72", "#1e272e"],
    "build":        ["#ffa502", "#ff6b35", "#eccc68"],
    "pre_chorus":   ["#ff9ff3", "#feca57", "#48dbfb"],
    "breakdown":    ["#2c3e50", "#34495e", "#7f8c8d"],
}
DEFAULT_PALETTE = ["#2d3436", "#636e72"]

TRANSITION_COLOR = {
    "drop":         "#ffffff",
    "impact":       "#ffffff",
    "riser":        "#ffa500",
    "buildup":      "#ffff00",
    "filter_sweep": "#00ffff",
    "stop":         "#000000",
    "key_change":   "#ff00ff",
}


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def find_section(t: float, sections: list) -> dict:
    for s in sections:
        if s["start"] <= t < s["end"]:
            return s
    return sections[-1]


def find_vocal(t: float, vocals: list) -> dict | None:
    for v in vocals:
        if v["start"] <= t < v["end"]:
            return v
    return None


def find_transition(t: float, transitions: list, tol: float = 0.25) -> dict | None:
    for tr in transitions:
        if abs(tr["time"] - t) <= tol:
            return tr
    return None


def build_cut_times(tl: dict, duration: float) -> list[float]:
    bpm = tl["summary"]["bpm_estimate"]
    beat = 60.0 / bpm
    cuts: set[float] = set()
    t = 0.0
    while t <= duration + 1e-6:
        cuts.add(round(t, 3))
        t += beat
    for tr in tl.get("transitions", []):
        cuts.add(round(tr["time"], 3))
    for s in tl.get("sections", []):
        cuts.add(round(s["start"], 3))
        cuts.add(round(s["end"], 3))
    for v in tl.get("vocal_events", []):
        cuts.add(round(v["start"], 3))
        cuts.add(round(v["end"], 3))

    ordered = sorted(c for c in cuts if 0 <= c <= duration)
    if ordered[0] != 0.0:
        ordered.insert(0, 0.0)
    if ordered[-1] < duration:
        ordered.append(duration)

    filtered = [ordered[0]]
    for c in ordered[1:]:
        if c - filtered[-1] >= MIN_SEG:
            filtered.append(c)
    if filtered[-1] < duration:
        filtered[-1] = duration
    return filtered


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    line = words[0]
    for w in words[1:]:
        candidate = f"{line} {w}"
        bbox = font.getbbox(candidate)
        if bbox[2] - bbox[0] <= max_width:
            line = candidate
        else:
            lines.append(line)
            line = w
    lines.append(line)
    return lines


def draw_centered_block(
    img: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    y_center: int,
    fill: tuple[int, int, int],
    box_fill: tuple[int, int, int, int] | None,
    line_spacing: int = 10,
    pad: int = 24,
) -> None:
    line_heights = []
    line_widths = []
    for ln in lines:
        bbox = font.getbbox(ln)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])
    total_h = sum(line_heights) + line_spacing * (len(lines) - 1)
    max_w = max(line_widths) if line_widths else 0
    top = y_center - total_h // 2

    if box_fill is not None:
        box = [
            (W - max_w) // 2 - pad,
            top - pad,
            (W + max_w) // 2 + pad,
            top + total_h + pad,
        ]
        img.rectangle(box, fill=box_fill)

    y = top
    for ln, lw, lh in zip(lines, line_widths, line_heights):
        x = (W - lw) // 2
        img.text((x, y - font.getbbox(ln)[1]), ln, font=font, fill=fill)
        y += lh + line_spacing


def render_card(
    out_path: Path,
    color_hex: str,
    big_text: str,
    sub_text: str,
    corner_text: str,
) -> None:
    bg = hex_to_rgb(color_hex)
    text_fill = (255, 255, 255) if luminance(bg) < 140 else (20, 20, 20)
    shadow_fill = (0, 0, 0, 140) if luminance(bg) >= 140 else (0, 0, 0, 110)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img, "RGBA")

    big_font = ImageFont.truetype(FONT_BLACK, 92)
    big_lines = wrap_text(big_text, big_font, int(W * 0.85))
    # shrink if too many lines
    while len(big_lines) > 3 and big_font.size > 44:
        big_font = ImageFont.truetype(FONT_BLACK, big_font.size - 8)
        big_lines = wrap_text(big_text, big_font, int(W * 0.85))
    draw_centered_block(draw, big_lines, big_font, H // 2 - 40, text_fill, shadow_fill, line_spacing=14, pad=28)

    sub_font = ImageFont.truetype(FONT, 30)
    sub_lines = wrap_text(sub_text, sub_font, int(W * 0.85))[:3]
    draw_centered_block(draw, sub_lines, sub_font, H - 130, text_fill, (0, 0, 0, 120), line_spacing=8, pad=18)

    corner_font = ImageFont.truetype(FONT_BOLD, 24)
    corner_bbox = corner_font.getbbox(corner_text)
    cw = corner_bbox[2] - corner_bbox[0]
    ch = corner_bbox[3] - corner_bbox[1]
    draw.rectangle([24, 24, 24 + cw + 24, 24 + ch + 24], fill=(0, 0, 0, 140))
    draw.text((36, 36 - corner_bbox[1]), corner_text, font=corner_font, fill=text_fill)

    img.save(out_path, "PNG")


def render_segment_video(png_path: Path, out_path: Path, dur: float) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-framerate", str(FPS),
        "-t", f"{dur:.4f}",
        "-i", str(png_path),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        "-r", str(FPS),
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def main() -> int:
    tl_path = Path(sys.argv[1])
    audio_path = Path(sys.argv[2])
    out_path = Path(sys.argv[3])

    tl = json.loads(tl_path.read_text())
    duration = max(s["end"] for s in tl["sections"])
    cut_times = build_cut_times(tl, duration)
    print(f"[cuts] {len(cut_times) - 1} segments over {duration:.2f}s (bpm={tl['summary']['bpm_estimate']})")

    with tempfile.TemporaryDirectory(prefix="mograph_cuts_") as td:
        tmp = Path(td)
        concat_file = tmp / "list.txt"
        lines: list[str] = []
        per_section_idx: dict[int, int] = {}

        for i in range(len(cut_times) - 1):
            start = cut_times[i]
            end = cut_times[i + 1]
            section = find_section(start, tl["sections"])
            vocal = find_vocal(start, tl.get("vocal_events", []))
            transition = find_transition(start, tl.get("transitions", []))

            sec_key = id(section)
            per_section_idx[sec_key] = per_section_idx.get(sec_key, 0) + 1
            palette = PALETTES.get(section["label"], DEFAULT_PALETTE)
            color = palette[per_section_idx[sec_key] % len(palette)]
            if transition is not None:
                color = TRANSITION_COLOR.get(transition["type"], color)

            big = vocal["lyric_or_description"].upper() if vocal else section["label"].upper()
            if transition:
                big = f"[{transition['type'].upper()}]"

            sub = section["visual_prompt"]
            corner = (
                f"{start:05.2f}-{end:05.2f}s  |  {section['label']}  |  "
                f"energy {section['energy']:.1f}  |  beat {i + 1}/{len(cut_times) - 1}"
            )

            png = tmp / f"card_{i:03d}.png"
            seg = tmp / f"seg_{i:03d}.mp4"
            render_card(png, color, big, sub, corner)
            render_segment_video(png, seg, end - start)
            lines.append(f"file '{seg}'")
            print(f"  seg {i:03d}  {start:05.2f}-{end:05.2f}  {color}  {section['label']:<12}  {big[:42]}")

        concat_file.write_text("\n".join(lines) + "\n")

        concat_video = tmp / "concat.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(concat_video),
        ], check=True)

        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(concat_video),
            "-i", str(audio_path),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(out_path),
        ], check=True)

    print(f"[done] {out_path}  ({os.path.getsize(out_path) / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
