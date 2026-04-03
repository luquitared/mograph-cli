"""Ref resolution utilities for the timeline executor.

Resolves Ref and FrameInput values to concrete file paths, handling
extract operations (first_frame, last_frame, audio) via shared/media.py.
"""

import logging
from pathlib import Path
from typing import Dict, Optional

from timeline.model import FrameInput, Generate, NodeResult, Ref

logger = logging.getLogger(__name__)

# Mapping of extract types to file extensions
_EXTRACT_EXTENSIONS = {
    "first_frame": ".png",
    "last_frame": ".png",
    "audio": ".aac",
}


def resolve_ref(
    ref: Ref,
    results: Dict[str, NodeResult],
    run_dir: Path,
) -> Path:
    """Resolve a Ref to a concrete file path.

    - Basic ref (no extract): returns results[ref.ref].path directly.
    - extract="first_frame": extracts the first frame from the referenced video.
    - extract="last_frame": extracts the last frame from the referenced video.
    - extract="audio": extracts the audio track from the referenced video.

    Extracted files are written to run_dir/extracted_frames/{ref}_{extract}.ext.

    Raises:
        KeyError: If the referenced node has no result.
        ValueError: If the extract type is unknown.
    """
    ref_id = ref.ref
    if ref_id not in results:
        raise KeyError(f"Ref '{ref_id}' not found in results")

    source_path = results[ref_id].path

    if ref.extract is None:
        return source_path

    extract = ref.extract
    ext = _EXTRACT_EXTENSIONS.get(extract)
    if ext is None:
        raise ValueError(f"Unknown extract type: {extract!r}")

    # Build destination path
    extracted_dir = run_dir / "extracted_frames"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    dest = extracted_dir / f"{ref_id}_{extract}{ext}"

    # Return cached extraction if it already exists
    if dest.exists():
        return dest

    from shared.media import extract_audio_track, extract_first_frame, extract_last_frame

    if extract == "first_frame":
        extract_first_frame(source_path, dest)
    elif extract == "last_frame":
        extract_last_frame(source_path, dest)
    elif extract == "audio":
        extract_audio_track(source_path, dest)

    logger.info("Extracted %s from %s → %s", extract, ref_id, dest)
    return dest


def resolve_frame_input(
    frame_input: FrameInput,
    results: Dict[str, NodeResult],
    run_dir: Path,
) -> Optional[Path]:
    """Resolve a first_frame or last_frame value to a concrete file path.

    - None → None
    - str → Path(str) directly (literal file path)
    - Ref → resolve_ref()
    - Generate → None (executor handles inline generates via anonymous nodes)
    """
    if frame_input is None:
        return None

    if isinstance(frame_input, str):
        return Path(frame_input)

    if isinstance(frame_input, Ref):
        return resolve_ref(frame_input, results, run_dir)

    if isinstance(frame_input, Generate):
        # Generate objects create anonymous DAG nodes (__anon_N).
        # The executor dispatches these before the parent video node,
        # so by the time we resolve frame input the anon result is
        # already in `results`. The DAG edge ensures ordering.
        # Return None here — the executor resolves Generate via the
        # anonymous node's result directly.
        return None

    return None
