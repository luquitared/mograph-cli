#!/usr/bin/env python3
"""
Shared utilities for batch scripts.

Provides a small set of helpers used across batch runners and pipelines
to reduce duplication and make programmatic composition easier.
"""
import base64
import mimetypes
import re
from pathlib import Path


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def guess_mime_image(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".png"}:
        return "image/png"
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext in {".webp"}:
        return "image/webp"
    return "application/octet-stream"


def sanitize_filename(s: str, max_len: int = 60) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-_]+", "", s)
    return s[:max_len] or "video"


def slugify_identifier(value: str, fallback: str = "item") -> str:
    """Return a filesystem-friendly slug preserving simple separators."""
    value = (value or "").lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")
    return value or fallback


def encode_image_as_data_url(path: Path) -> dict:
    """Encode image as base64 data URL for API input."""
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "input_image", "image_url": f"data:{mime};base64,{data}"}

