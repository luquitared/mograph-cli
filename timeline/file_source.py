"""File source adapter for timeline execution.

Resolves FileSource objects to concrete paths with duration — handles local
files (relative to timeline directory) and URL downloads, with optional
segment extraction.
"""

import asyncio
import logging
import socket
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlparse

import aiohttp
import aiohttp.abc

from shared.media import extract_audio_segment, probe_duration_async
from timeline import is_url
from timeline.model import FileSource, NodeResult
from timeline.security import SecurityError, validate_path, validate_url

logger = logging.getLogger(__name__)

# Extension → media type mapping
_VIDEO_EXTS = frozenset({".mp4", ".mov", ".webm", ".avi", ".mkv"})
_AUDIO_EXTS = frozenset({".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"})
_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})

# Maximum download size: 500 MB
MAX_DOWNLOAD_SIZE = 500 * 1024 * 1024


class _PinnedResolver(aiohttp.abc.AbstractResolver):
    """DNS resolver that returns pre-validated IPs instead of resolving."""

    def __init__(self, ips: List[str]):
        self._ips = ips

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        return [
            {
                "hostname": host,
                "host": ip,
                "port": port,
                "family": socket.AF_INET,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST,
            }
            for ip in self._ips
        ]

    async def close(self):
        pass


def _infer_media_type(path: Path) -> str:
    """Infer media type from file extension."""
    ext = path.suffix.lower()
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _IMAGE_EXTS:
        return "image"
    return "video"  # default fallback


async def _download_file(
    url: str, dest: Path, session: aiohttp.ClientSession
) -> Path:
    """Download a URL to a local path with size limit enforcement."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with session.get(url) as resp:
        resp.raise_for_status()
        bytes_read = 0
        with open(dest, "wb") as f:
            async for chunk in resp.content.iter_chunked(8192):
                bytes_read += len(chunk)
                if bytes_read > MAX_DOWNLOAD_SIZE:
                    dest.unlink(missing_ok=True)
                    raise SecurityError(
                        f"Download exceeds maximum size of {MAX_DOWNLOAD_SIZE} bytes: {url}"
                    )
                f.write(chunk)
    return dest


async def _resolve_single(
    clip_id: str,
    source: FileSource,
    run_dir: Path,
    timeline_dir: Path,
    session: aiohttp.ClientSession,
) -> NodeResult:
    """Resolve a single FileSource to a NodeResult."""
    raw_path = source.path

    if is_url(raw_path):
        # SSRF prevention — validate_url returns pinned IPs
        validate_url(raw_path)

        # Download to run_dir/downloads/
        parsed = urlparse(raw_path)
        filename = Path(parsed.path).name or "download"
        dest = run_dir / "downloads" / f"{clip_id}_{filename}"
        local_path = await _download_file(raw_path, dest, session)
        logger.info("Downloaded %s → %s", raw_path, local_path)
    else:
        # Local file — resolve relative to CWD
        candidate = Path.cwd() / raw_path
        local_path = validate_path(candidate, Path.cwd())
        if not local_path.exists():
            raise FileNotFoundError(
                f"File source not found: {raw_path} (resolved to {local_path})"
            )

    # Segment extraction
    if source.start is not None or source.end is not None:
        start = source.start or 0.0
        # If end is not set, probe full duration
        if source.end is None:
            full_dur = await probe_duration_async(local_path)
            end = full_dur
        else:
            end = source.end

        # extract_audio_segment re-encodes to AAC, so the container has to be
        # one that accepts AAC. Keeping the source suffix meant an .mp3 music
        # bed produced "aac into .mp3", which ffmpeg rejects outright:
        # "Invalid audio stream. Exactly one MP3 audio stream is required."
        seg_dest = run_dir / "segments" / (
            f"{clip_id}_segment"
            + (".m4a" if _infer_media_type(local_path) == "audio"
               else local_path.suffix)
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, extract_audio_segment, local_path, start, end, seg_dest
        )
        local_path = seg_dest
        duration = end - start
    else:
        duration = await probe_duration_async(local_path)

    media_type = _infer_media_type(local_path)

    return NodeResult(
        path=local_path,
        duration=duration,
        media_type=media_type,
    )


async def resolve_file_sources(
    sources: List[Tuple[str, FileSource]],
    run_dir: Path,
    timeline_dir: Path,
) -> Dict[str, NodeResult]:
    """Resolve file sources to concrete paths with duration.

    Returns mapping of clip ID → NodeResult.
    """
    if not sources:
        return {}

    # Validate URLs and collect pinned IPs before creating sessions
    all_ips: List[str] = []
    has_urls = False
    for _, source in sources:
        if is_url(source.path):
            has_urls = True
            ips = validate_url(source.path)
            all_ips.extend(ips)

    # Use pinned resolver for URL downloads to prevent DNS rebinding
    if has_urls and all_ips:
        connector = aiohttp.TCPConnector(resolver=_PinnedResolver(all_ips))
    else:
        connector = None

    sem = asyncio.Semaphore(10)

    async def _resolve_one(
        clip_id: str, source: FileSource, session: aiohttp.ClientSession
    ) -> Tuple[str, NodeResult]:
        async with sem:
            result = await _resolve_single(
                clip_id, source, run_dir, timeline_dir, session
            )
            logger.info(
                "Resolved file source %s: %s (%.2fs, %s)",
                clip_id, result.path, result.duration or 0, result.media_type,
            )
            return clip_id, result

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _resolve_one(clip_id, source, session)
            for clip_id, source in sources
        ]
        completed = await asyncio.gather(*tasks)

    return {clip_id: result for clip_id, result in completed}
