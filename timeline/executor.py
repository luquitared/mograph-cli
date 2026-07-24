"""DAG executor for timeline-based video generation.

Walks the dependency graph built by ``dag.py``, dispatches generation jobs
to the appropriate adapters (image, video, TTS, file, silence, still),
and collects results.  The public entry point is :func:`execute_timeline`.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from timeline.model import (
    Clip,
    FileSource,
    Generate,
    ImageSource,
    NodeResult,
    Project,
    Ref,
    SilenceSource,
    Source,
    StillSource,
    TTSSource,
    Timeline,
    Track,
    VerificationEntry,
    VideoSource,
)
from timeline.verifier import should_verify, verify_media, write_verification_results
from timeline.dag import DAG, DAGNode, build_dag_with_identity_map, topological_sort
from timeline.validator import validate
from timeline.timing import compute_timeline_timing, ClipLayout, TimelineLayout
from timeline.fitter import apply_fit
from timeline.run_context import (
    is_stage_complete,
    mark_stage_complete,
    record_cost,
)
from timeline.assembler import assemble_timeline
from timeline.explorer import (
    CandidateInfo,
    ExplorationState,
    PendingSelection,
    SelectionManifest,
    get_selected_paths,
    read_manifest,
    read_selections,
    validate_selections,
    write_manifest,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RunResult
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Outcome of a timeline execution run."""
    run_dir: Path
    results: Dict[str, NodeResult] = field(default_factory=dict)
    stage: str = "final"
    success: bool = True
    errors: List[str] = field(default_factory=list)
    layout: Optional[TimelineLayout] = None
    outputs: Dict[str, Path] = field(default_factory=dict)
    pending_exploration: Optional[str] = None  # phase name needing selection, if paused


# ---------------------------------------------------------------------------
# Cost constants (imported from shared/costs.py when available)
# ---------------------------------------------------------------------------

try:
    from shared.costs import IMAGE_COST_USD, VIDEO_SECOND_COST_USD, TTS_COST_USD
except ImportError:  # pragma: no cover
    IMAGE_COST_USD = 0.15
    VIDEO_SECOND_COST_USD = 0.15
    TTS_COST_USD = 0.0


# ---------------------------------------------------------------------------
# Stage filtering
# ---------------------------------------------------------------------------

# Source types included in each stage
_STAGE_SOURCE_TYPES: Dict[str, Set[str]] = {
    "images": {"image", "tts", "file", "silence"},
    "videos": {"image", "tts", "file", "silence", "video", "still"},
    "final":  {"image", "tts", "file", "silence", "video", "still"},
}


def _source_type_for_node(
    node_id: str,
    source_map: Dict[str, Source],
) -> Optional[str]:
    """Return the source type string for a node, or None if unknown."""
    source = source_map.get(node_id)
    if source is None:
        return None
    return getattr(source, "type", None)


def _node_passes_stage(
    node_id: str,
    source_map: Dict[str, Source],
    stage: str,
) -> bool:
    """Check whether a node should be executed in the given stage."""
    stype = _source_type_for_node(node_id, source_map)
    if stype is None:
        # Unknown source — include it (e.g. anonymous nodes inherit their source type)
        return True
    allowed = _STAGE_SOURCE_TYPES.get(stage)
    if allowed is None:
        return True
    return stype in allowed


# ---------------------------------------------------------------------------
# Source map builder — maps node IDs to their Source objects
# ---------------------------------------------------------------------------

def _build_source_map(
    timeline: Timeline, anon_identity_map: Dict[int, str]
) -> Dict[str, Source]:
    """Build a flat mapping of node_id → Source.

    Uses the anon_identity_map from build_dag() to populate anonymous node sources.
    """
    source_map: Dict[str, Source] = {}

    # Assets
    for asset_id, source in timeline.assets.items():
        source_map[asset_id] = source

    # Clips
    for track in timeline.tracks:
        for clip in track.clips:
            if clip.id and clip.source:
                source_map[clip.id] = clip.source

    # Anonymous Generate nodes — use the identity map from build_dag()
    _populate_anon_sources(timeline, source_map, anon_identity_map)

    return source_map


def _populate_anon_sources(
    timeline: Timeline,
    source_map: Dict[str, Source],
    anon_identity_map: Dict[int, str],
) -> None:
    """Populate source_map entries for anonymous nodes using the DAG identity map."""
    for _asset_id, source in timeline.assets.items():
        _populate_anon_from_source(source, source_map, anon_identity_map)
    for track in timeline.tracks:
        for clip in track.clips:
            if clip.id and clip.source:
                _populate_anon_from_source(clip.source, source_map, anon_identity_map)


def _populate_anon_from_source(
    source: Source,
    source_map: Dict[str, Source],
    anon_identity_map: Dict[int, str],
) -> None:
    """Recursively populate anonymous node sources from a single source."""
    if isinstance(source, VideoSource):
        _populate_anon_from_frame_input(source.first_frame, source_map, anon_identity_map)
        _populate_anon_from_frame_input(source.last_frame, source_map, anon_identity_map)


def _populate_anon_from_frame_input(
    frame_input: Any,
    source_map: Dict[str, Source],
    anon_identity_map: Dict[int, str],
) -> None:
    """Process a frame input for anonymous Generate sources."""
    if frame_input is None or isinstance(frame_input, (str, Ref)):
        return
    if isinstance(frame_input, Generate) and frame_input.generate is not None:
        anon_id = anon_identity_map.get(id(frame_input))
        if anon_id is not None:
            source_map[anon_id] = frame_input.generate
            # Recurse into the generated source
            _populate_anon_from_source(frame_input.generate, source_map, anon_identity_map)


# ---------------------------------------------------------------------------
# Batch grouping
# ---------------------------------------------------------------------------

def _group_by_source_type(
    node_ids: List[str],
    source_map: Dict[str, Source],
) -> Dict[str, List[str]]:
    """Group node IDs by their source type string."""
    groups: Dict[str, List[str]] = {}
    for nid in node_ids:
        stype = _source_type_for_node(nid, source_map)
        if stype is None:
            logger.warning("Node %s has no source — skipping", nid)
            continue
        groups.setdefault(stype, []).append(nid)
    return groups


# ---------------------------------------------------------------------------
# Dispatch helpers — call the appropriate adapter for each source type
# ---------------------------------------------------------------------------

async def _dispatch_images(
    node_ids: List[str],
    source_map: Dict[str, Source],
    results: Dict[str, NodeResult],
    run_dir: Path,
    timeline: Timeline,
    concurrency: int,
) -> Dict[str, NodeResult]:
    """Dispatch a batch of image generation nodes."""
    from timeline.image_gen import generate_images
    from timeline.resolver import resolve_ref

    # Resolve any Ref items in reference_images to concrete paths
    resolved_sources: List[tuple] = []
    for nid in node_ids:
        source: ImageSource = source_map[nid]
        resolved_refs = []
        for item in source.reference_images:
            if isinstance(item, Ref):
                path = resolve_ref(item, results, run_dir)
                resolved_refs.append(str(path))
            else:
                resolved_refs.append(item)
        # Shallow-copy the source with resolved paths
        resolved = ImageSource(
            prompt=source.prompt,
            reference_images=resolved_refs,
            model=source.model,
            aspect_ratio=source.aspect_ratio,
            resolution=source.resolution,
            output_format=source.output_format,
            safety_filter_level=source.safety_filter_level,
            quality=source.quality,
            background=source.background,
            output_compression=source.output_compression,
            moderation=source.moderation,
            number_of_images=source.number_of_images,
            candidates=source.candidates,
            select=source.select,
            verify=source.verify,
        )
        resolved_sources.append((nid, resolved))

    return await generate_images(resolved_sources, run_dir, timeline.defaults.image, concurrency)


async def _dispatch_videos(
    node_ids: List[str],
    source_map: Dict[str, Source],
    results: Dict[str, NodeResult],
    run_dir: Path,
    timeline: Timeline,
    concurrency: int,
    anon_identity_map: Dict[int, str],
) -> Dict[str, NodeResult]:
    """Dispatch a batch of video generation nodes."""
    from timeline.video_gen import VideoJob, generate_videos
    from timeline.resolver import resolve_frame_input

    jobs: List[VideoJob] = []
    for nid in node_ids:
        source: VideoSource = source_map[nid]

        # Resolve frame inputs — for Generate refs, look up the anon node result
        first_path = _resolve_video_frame(source.first_frame, results, run_dir, anon_identity_map)
        last_path = _resolve_video_frame(source.last_frame, results, run_dir, anon_identity_map)

        # Resolve reference image paths — strings or Ref objects
        ref_img_paths = []
        for ref_img in getattr(source, "reference_images", []):
            if isinstance(ref_img, Ref):
                from timeline.resolver import resolve_ref
                p = resolve_ref(ref_img, results, run_dir)
                ref_img_paths.append(p)
            else:
                p = Path(ref_img).expanduser().resolve()
                if p.exists():
                    ref_img_paths.append(p)
                else:
                    logger.warning("Reference image not found: %s", p)

        # Resolve reference video paths — strings or Ref objects (video-to-video chaining)
        ref_vid_paths = []
        for ref_vid in getattr(source, "reference_videos", []):
            if isinstance(ref_vid, Ref):
                from timeline.resolver import resolve_ref
                p = resolve_ref(ref_vid, results, run_dir)
                ref_vid_paths.append(p)
            else:
                p = Path(ref_vid).expanduser().resolve()
                if p.exists():
                    ref_vid_paths.append(p)
                else:
                    logger.warning("Reference video not found: %s", p)

        # Resolve reference audio paths
        ref_aud_paths = []
        for ref_aud in getattr(source, "reference_audios", []):
            p = Path(ref_aud).expanduser().resolve()
            if p.exists():
                ref_aud_paths.append(p)
            else:
                logger.warning("Reference audio not found: %s", p)

        jobs.append(VideoJob(
            clip_id=nid,
            source=source,
            first_frame_path=first_path,
            last_frame_path=last_path,
            reference_image_paths=ref_img_paths,
            reference_video_paths=ref_vid_paths,
            reference_audio_paths=ref_aud_paths,
        ))

    return await generate_videos(jobs, run_dir, timeline.defaults.video, concurrency)


def _resolve_video_frame(
    frame_input: Any,
    results: Dict[str, NodeResult],
    run_dir: Path,
    anon_identity_map: Dict[int, str],
) -> Optional[Path]:
    """Resolve a video's first_frame/last_frame, including Generate lookups."""
    from timeline.resolver import resolve_frame_input

    if isinstance(frame_input, Generate) and frame_input.generate is not None:
        # Look up the anonymous node ID via the identity mapping
        anon_id = anon_identity_map.get(id(frame_input))
        if anon_id is not None:
            result = results.get(anon_id)
            if result is not None and result.path is not None:
                return result.path
        return None

    return resolve_frame_input(frame_input, results, run_dir)


async def _dispatch_tts(
    node_ids: List[str],
    source_map: Dict[str, Source],
    run_dir: Path,
    timeline: Timeline,
    concurrency: int,
) -> Dict[str, NodeResult]:
    """Dispatch a batch of TTS generation nodes."""
    from timeline.tts_gen import generate_tts

    sources = [(nid, source_map[nid]) for nid in node_ids]
    return await generate_tts(
        sources, run_dir, timeline.defaults.tts, timeline.project, concurrency
    )


async def _dispatch_files(
    node_ids: List[str],
    source_map: Dict[str, Source],
    run_dir: Path,
    timeline_dir: Optional[Path],
) -> Dict[str, NodeResult]:
    """Dispatch a batch of file source resolutions."""
    from timeline.file_source import resolve_file_sources

    sources = [(nid, source_map[nid]) for nid in node_ids]
    tdir = timeline_dir or Path(".")
    return await resolve_file_sources(sources, run_dir, tdir)


async def _dispatch_silence(
    node_ids: List[str],
    source_map: Dict[str, Source],
    run_dir: Path,
) -> Dict[str, NodeResult]:
    """Dispatch a batch of silence generation nodes."""
    from timeline.silence_gen import generate_silence_clips

    sources = [(nid, source_map[nid]) for nid in node_ids]
    return await generate_silence_clips(sources, run_dir)


async def _dispatch_still(
    node_ids: List[str],
    source_map: Dict[str, Source],
    run_dir: Path,
    results: Dict[str, NodeResult],
) -> Dict[str, NodeResult]:
    """Dispatch a batch of still-to-video conversions."""
    from timeline.still_gen import generate_still_videos

    sources = [(nid, source_map[nid]) for nid in node_ids]
    return await generate_still_videos(sources, run_dir, results)


# ---------------------------------------------------------------------------
# Failed-node tracking
# ---------------------------------------------------------------------------

def _get_failed_dependents(
    failed_ids: Set[str],
    dag: DAG,
) -> Set[str]:
    """Return all node IDs that transitively depend on any failed node."""
    # Build reverse adjacency: dependency → set of dependents
    dependents_of: Dict[str, List[str]] = {}
    for from_id, to_id in dag.edges:
        dependents_of.setdefault(to_id, []).append(from_id)

    skipped: Set[str] = set()
    queue = list(failed_ids)
    while queue:
        nid = queue.pop()
        for dep in dependents_of.get(nid, []):
            if dep not in skipped and dep not in failed_ids:
                skipped.add(dep)
                queue.append(dep)

    return skipped


# ---------------------------------------------------------------------------
# Resume support helpers
# ---------------------------------------------------------------------------


def _probe_or_none(path: Path) -> Optional[float]:
    """Duration of an existing media file, or None if it can't be read.

    Resumed nodes must carry a real duration. Without one, `fit_to` targets
    resolve to 0.0, `apply_fit` divides by zero, the exception is swallowed as a
    warning, and the video is assembled shorter than its narration — the tail of
    the voiceover is silently dropped. See docs/reference/known-issues.md §1.
    """
    try:
        from shared.media import probe_duration
        return probe_duration(path)
    except Exception as exc:  # noqa: BLE001 — a bad probe must not kill resume
        logger.warning("Could not probe duration for %s: %s", path, exc)
        return None


def _load_existing_results(run_dir: Path) -> Dict[str, NodeResult]:
    """Load existing results from a previous run for resume support."""
    results: Dict[str, NodeResult] = {}

    # Scan images/
    images_dir = run_dir / "images"
    if images_dir.exists():
        for p in images_dir.iterdir():
            if p.is_file() and p.suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                clip_id = p.stem
                results[clip_id] = NodeResult(path=p, duration=None, media_type="image")

    # Scan videos/
    videos_dir = run_dir / "videos"
    if videos_dir.exists():
        for p in videos_dir.iterdir():
            if p.is_file() and p.suffix == ".mp4":
                clip_id = p.stem.removesuffix("_still")
                results[clip_id] = NodeResult(
                    path=p, duration=_probe_or_none(p), media_type="video"
                )

    # Scan audio/
    audio_dir = run_dir / "audio"
    if audio_dir.exists():
        for p in audio_dir.iterdir():
            if p.is_file() and p.suffix in {".mp3", ".wav"} and not p.stem.endswith(".timestamps"):
                clip_id = p.stem.removesuffix("_silence")
                results[clip_id] = NodeResult(
                    path=p, duration=_probe_or_none(p), media_type="audio"
                )

    return results


# ---------------------------------------------------------------------------
# Cost recording helper
# ---------------------------------------------------------------------------

def _record_batch_cost(
    run_dir: Path,
    stype: str,
    successful_nodes: List[str],
    batch_results: Dict[str, NodeResult],
) -> None:
    """Record generation costs for a successful batch."""
    if stype == "image":
        amount = len(successful_nodes) * IMAGE_COST_USD
        if amount > 0:
            record_cost(run_dir, "image", amount,
                        f"{len(successful_nodes)} image(s)",
                        {"nodes": successful_nodes})
    elif stype == "video":
        total_seconds = sum(
            (batch_results[nid].duration or 0.0) for nid in successful_nodes
        )
        amount = total_seconds * VIDEO_SECOND_COST_USD
        if amount > 0:
            record_cost(run_dir, "video", amount,
                        f"{len(successful_nodes)} video(s), {total_seconds:.1f}s total",
                        {"nodes": successful_nodes, "total_seconds": total_seconds})
    elif stype == "tts":
        amount = len(successful_nodes) * TTS_COST_USD
        if amount > 0:
            record_cost(run_dir, "tts", amount,
                        f"{len(successful_nodes)} TTS clip(s)",
                        {"nodes": successful_nodes})
    # file, silence, still: no cost


# ---------------------------------------------------------------------------
# Fit adjustment helper
# ---------------------------------------------------------------------------

async def _apply_fit_for_clip(
    clip_id: str,
    clip_layout: ClipLayout,
    node_result: NodeResult,
    run_dir: Path,
) -> Tuple[str, Path]:
    """Apply fit adjustment to a single clip. Returns (clip_id, adjusted_path)."""
    adjusted = await apply_fit(
        clip_path=node_result.path,
        method=clip_layout.fit_method,
        raw_duration=clip_layout.raw_duration,
        target_duration=clip_layout.final_duration,
        media_type=node_result.media_type,
        run_dir=run_dir,
        clip_id=clip_id,
    )
    return (clip_id, adjusted)


# ---------------------------------------------------------------------------
# Source-type-to-phase mapping
# ---------------------------------------------------------------------------

_SOURCE_TYPE_TO_PHASE: Dict[str, str] = {
    "image": "images",
    "video": "videos",
    "tts": "tts",
}

# Phase processing order
_PHASE_ORDER = ["images", "videos", "tts"]


# ---------------------------------------------------------------------------
# Candidate generation helper
# ---------------------------------------------------------------------------

def _get_prompt_for_source(source: Source) -> str:
    """Extract the prompt/text from a source for CandidateInfo."""
    if isinstance(source, ImageSource):
        return source.prompt
    elif isinstance(source, VideoSource):
        return source.prompt
    elif isinstance(source, TTSSource):
        return source.text
    return ""



# Allowlist of fields that candidate overrides may set per source type.
# Dangerous fields (reference_images, model, first_frame, last_frame, path,
# candidates, select, type) are intentionally excluded to prevent file
# exfiltration or redirection to arbitrary endpoints.
_CANDIDATE_OVERRIDE_ALLOWLIST: Dict[str, Set[str]] = {
    "image": {"prompt", "aspect_ratio", "resolution", "output_format", "safety_filter_level"},
    "video": {"prompt", "negative_prompt", "seed", "duration", "aspect_ratio", "resolution", "generate_audio", "quality"},
    "tts": {"text", "voice", "voice_prompt"},
}


def _get_media_type_for_source(source: Source) -> str:
    """Return media type string for a source."""
    if isinstance(source, ImageSource):
        return "image"
    elif isinstance(source, VideoSource):
        return "video"
    elif isinstance(source, TTSSource):
        return "audio"
    return ""


async def _generate_single_candidate(
    candidate_index: int,
    overrides: Dict[str, Any],
    node_id: str,
    source: Source,
    run_dir: Path,
    timeline: Timeline,
    results: Dict[str, NodeResult],
    anon_identity_map: Dict[int, str],
) -> Optional[CandidateInfo]:
    """Generate a single candidate variant. Returns CandidateInfo or None."""
    from dataclasses import replace

    candidate_id = f"{node_id}_candidate_{candidate_index}"
    try:
        # Filter overrides to allowlisted fields only
        allowed = _CANDIDATE_OVERRIDE_ALLOWLIST.get(source.type, set())
        filtered = {k: v for k, v in overrides.items() if k in allowed}
        rejected = set(overrides) - allowed
        if rejected:
            logger.warning(
                "Candidate %s: rejected disallowed override keys: %s",
                candidate_id, rejected,
            )

        variant_source = replace(source, **filtered)

        # Generate using appropriate dispatch
        if isinstance(source, ImageSource):
            batch_results = await _dispatch_images(
                [candidate_id], {candidate_id: variant_source},
                results, run_dir, timeline, 1,
            )
        elif isinstance(source, VideoSource):
            batch_results = await _dispatch_videos(
                [candidate_id], {candidate_id: variant_source},
                results, run_dir, timeline, 1, anon_identity_map,
            )
        elif isinstance(source, TTSSource):
            batch_results = await _dispatch_tts(
                [candidate_id], {candidate_id: variant_source},
                run_dir, timeline, 1,
            )
        else:
            return None

        if candidate_id in batch_results:
            result = batch_results[candidate_id]
            results[candidate_id] = result
            return CandidateInfo(
                index=candidate_index,
                path=result.path,
                prompt=_get_prompt_for_source(variant_source),
            )
    except Exception as e:
        logger.warning("Candidate %s generation failed: %s", candidate_id, e)
    return None


async def _generate_candidates(
    node_id: str,
    source: Source,
    candidates_list: List[Dict[str, Any]],
    run_dir: Path,
    timeline: Timeline,
    results: Dict[str, NodeResult],
    anon_identity_map: Dict[int, str],
) -> List[CandidateInfo]:
    """Generate candidate variants for a node.

    The default generation (index 0) is already in results.
    This generates additional candidates from the overrides list
    and returns CandidateInfo for all variants (including the default).
    """
    default_result = results[node_id]
    default_prompt = _get_prompt_for_source(source)

    # Index 0 = the default already generated
    candidate_infos = [
        CandidateInfo(
            index=0,
            path=default_result.path,
            prompt=default_prompt,
        )
    ]

    # Generate all candidates concurrently
    tasks = [
        _generate_single_candidate(
            i + 1, overrides, node_id, source,
            run_dir, timeline, results, anon_identity_map,
        )
        for i, overrides in enumerate(candidates_list)
    ]
    generated = await asyncio.gather(*tasks)
    for info in generated:
        if info is not None:
            candidate_infos.append(info)

    return candidate_infos


def _apply_selections_to_results(
    selected_paths: Dict[str, List[Path]],
    results: Dict[str, NodeResult],
    source_map: Dict[str, Source],
) -> None:
    """Update results dict so each node points to its selected candidate path."""
    for node_id, paths in selected_paths.items():
        if not paths:
            continue
        # Use the first selected path (select=1 is the common case)
        selected_path = paths[0]
        old_result = results.get(node_id)
        if old_result:
            results[node_id] = NodeResult(
                path=selected_path,
                duration=old_result.duration,
                media_type=old_result.media_type,
            )


async def _handle_exploration_for_level(
    phase: str,
    nodes_with_candidates: List[Tuple[str, Source]],
    run_dir: Path,
    timeline: Timeline,
    results: Dict[str, NodeResult],
    source_map: Dict[str, Source],
    anon_identity_map: Dict[int, str],
    exploration_state: Optional[ExplorationState],
    run_result: RunResult,
) -> bool:
    """Handle candidate generation and selection for a phase.

    Returns True if execution should continue, False if it should pause/return early.
    """
    # Generate candidates for all nodes in this phase concurrently
    pending_selections: List[PendingSelection] = []

    # Filter to nodes that actually have candidates
    nodes_to_explore = [
        (node_id, source)
        for node_id, source in nodes_with_candidates
        if getattr(source, "candidates", None)
    ]

    if nodes_to_explore:
        # Launch all candidate generation tasks concurrently
        gen_tasks = [
            _generate_candidates(
                node_id=node_id,
                source=source,
                candidates_list=getattr(source, "candidates"),
                run_dir=run_dir,
                timeline=timeline,
                results=results,
                anon_identity_map=anon_identity_map,
            )
            for node_id, source in nodes_to_explore
        ]
        all_candidate_infos = await asyncio.gather(*gen_tasks)

        for (node_id, source), candidate_infos in zip(nodes_to_explore, all_candidate_infos):
            select_count = getattr(source, "select", None) or 1
            pending_selections.append(PendingSelection(
                id=node_id,
                type="asset" if node_id in timeline.assets else "clip",
                media_type=_get_media_type_for_source(source),
                select=select_count,
                candidates=candidate_infos,
            ))

    if not pending_selections:
        return True

    # Write manifest
    manifest = SelectionManifest(phase=phase, pending_selections=pending_selections)
    write_manifest(manifest, run_dir)

    if exploration_state is not None:
        # Cloud Run mode: pause and wait
        exploration_state.pause(phase)
        exploration_state.wait_for_selection()

        # After resume: read and apply selections
        selections = read_selections(run_dir, phase)
        if selections:
            errors = validate_selections(manifest, selections)
            if errors:
                run_result.errors.extend(errors)
                return True
            selected_paths = get_selected_paths(manifest, selections)
            _apply_selections_to_results(selected_paths, results, source_map)
        return True
    else:
        # CLI mode: check for existing selections file (resume)
        selections = read_selections(run_dir, phase)
        if selections:
            errors = validate_selections(manifest, selections)
            if errors:
                run_result.errors.extend(errors)
                return True
            selected_paths = get_selected_paths(manifest, selections)
            _apply_selections_to_results(selected_paths, results, source_map)
            return True
        else:
            # No selections — pause execution
            run_result.pending_exploration = phase
            return False


# ---------------------------------------------------------------------------
# Core async executor
# ---------------------------------------------------------------------------

async def _execute_async(
    timeline: Timeline,
    run_dir: Path,
    stage: str,
    concurrency: Optional[Dict[str, int]],
    resume: bool,
    timeline_dir: Optional[Path],
    exploration_state: Optional[ExplorationState] = None,
) -> RunResult:
    """Async implementation of the DAG executor."""
    run_result = RunResult(run_dir=run_dir, stage=stage)

    # Ensure run_dir exists
    run_dir.mkdir(parents=True, exist_ok=True)

    # Resume: skip if stage already complete
    # For 'final' stage, also check that assembly output actually exists
    if resume and is_stage_complete(run_dir, stage):
        final_output = run_dir / "final" / "final.mp4"
        if stage != "final" or final_output.exists():
            logger.info("Stage %r already complete — skipping", stage)
            run_result.results = _load_existing_results(run_dir)
            return run_result
        else:
            logger.info("Stage %r marked complete but final output missing — re-running assembly", stage)

    # Build DAG and source map
    dag, anon_identity_map = build_dag_with_identity_map(timeline)
    source_map = _build_source_map(timeline, anon_identity_map)
    levels = topological_sort(dag)

    # Concurrency defaults
    conc = concurrency or {}
    img_conc = conc.get("image", 4)
    vid_conc = conc.get("video", 3)
    tts_conc = conc.get("tts", 3)

    results: Dict[str, NodeResult] = {}
    failed_ids: Set[str] = set()
    skipped_ids: Set[str] = set()
    errors: List[str] = []
    verification_results: Dict[str, VerificationEntry] = {}

    # Load existing results for resume
    if resume:
        results.update(_load_existing_results(run_dir))

        # Apply any existing selections from a previous exploration pause
        for phase in _PHASE_ORDER:
            manifest = read_manifest(run_dir, phase)
            if manifest is None:
                continue
            selections = read_selections(run_dir, phase)
            if selections is None:
                continue
            sel_errors = validate_selections(manifest, selections)
            if sel_errors:
                errors.extend(sel_errors)
            else:
                selected_paths = get_selected_paths(manifest, selections)
                _apply_selections_to_results(selected_paths, results, source_map)

    # Walk DAG level by level
    for level_idx, level_nodes in enumerate(levels):
        # Filter nodes for this stage
        eligible = [
            nid for nid in level_nodes
            if nid not in skipped_ids
            and nid not in results  # skip already-completed (resume)
            and _node_passes_stage(nid, source_map, stage)
        ]

        if not eligible:
            continue

        # Check for nodes whose dependencies failed
        newly_skipped = set()
        for nid in eligible:
            node = dag.nodes.get(nid)
            if node and any(dep in failed_ids or dep in skipped_ids for dep in node.dependencies):
                newly_skipped.add(nid)
                skipped_ids.add(nid)
                errors.append(f"Skipped {nid}: dependency failed")
                logger.warning("Skipping %s: dependency failed", nid)

        eligible = [nid for nid in eligible if nid not in newly_skipped]
        if not eligible:
            continue

        # Group by source type for batch dispatch
        groups = _group_by_source_type(eligible, source_map)

        # Dispatch each group concurrently
        dispatch_pairs = []  # List of (source_type, node_ids, task)

        for stype, node_ids in groups.items():
            task = None
            if stype == "image":
                task = _dispatch_images(node_ids, source_map, results, run_dir, timeline, img_conc)
            elif stype == "video":
                task = _dispatch_videos(node_ids, source_map, results, run_dir, timeline, vid_conc, anon_identity_map)
            elif stype == "tts":
                task = _dispatch_tts(node_ids, source_map, run_dir, timeline, tts_conc)
            elif stype == "file":
                task = _dispatch_files(node_ids, source_map, run_dir, timeline_dir)
            elif stype == "silence":
                task = _dispatch_silence(node_ids, source_map, run_dir)
            elif stype == "still":
                task = _dispatch_still(node_ids, source_map, run_dir, results)
            else:
                logger.warning("Unknown source type %r for nodes %s", stype, node_ids)

            if task is not None:
                dispatch_pairs.append((stype, node_ids, task))

        dispatch_tasks = [pair[2] for pair in dispatch_pairs]

        # Run all dispatch groups for this level concurrently
        if dispatch_tasks:
            batch_results = await asyncio.gather(*dispatch_tasks, return_exceptions=True)

            for i, br in enumerate(batch_results):
                stype, expected_nodes, _ = dispatch_pairs[i]
                if isinstance(br, Exception):
                    for nid in expected_nodes:
                        failed_ids.add(nid)
                        errors.append(f"Failed {nid} ({stype}): {br}")
                        logger.error("Node %s failed: %s", nid, br)
                    # Propagate failures to dependents
                    new_skips = _get_failed_dependents(failed_ids, dag)
                    skipped_ids.update(new_skips)
                elif isinstance(br, dict):
                    successful_nodes = []
                    for nid in expected_nodes:
                        if nid in br:
                            results[nid] = br[nid]
                            successful_nodes.append(nid)
                        else:
                            # Node was dispatched but didn't produce a result
                            failed_ids.add(nid)
                            errors.append(f"Failed {nid} ({stype}): no result returned")
                            logger.error("Node %s produced no result", nid)

                    # Record costs for successful nodes
                    if successful_nodes:
                        _record_batch_cost(run_dir, stype, successful_nodes, br)

                    # --- Verification: check generated media against prompts ---
                    for nid in list(successful_nodes):
                        source = source_map.get(nid)
                        if source is None or not should_verify(source):
                            continue

                        node_result = results[nid]
                        max_retries = 3
                        logger.info("Verifying %s (%s)...", nid, stype)

                        entry = await verify_media(node_result.path, source, max_attempts=3)

                        if entry.passed:
                            verification_results[nid] = entry
                            continue

                        # Verification failed — retry generation up to max_retries
                        for retry in range(1, max_retries):
                            logger.warning(
                                "Verification failed for %s, regenerating (retry %d/%d): %s",
                                nid, retry, max_retries - 1, entry.reason,
                            )
                            # Re-dispatch single node
                            retry_result = None
                            try:
                                if stype == "image":
                                    retry_batch = await _dispatch_images([nid], source_map, results, run_dir, timeline, 1)
                                    retry_result = retry_batch.get(nid)
                                elif stype == "video":
                                    retry_batch = await _dispatch_videos(
                                        [nid], source_map, results, run_dir, timeline, 1, anon_identity_map,
                                    )
                                    retry_result = retry_batch.get(nid)
                            except Exception as e:
                                logger.error("Retry generation failed for %s: %s", nid, e)
                                break

                            if retry_result is None:
                                break

                            results[nid] = retry_result
                            entry = await verify_media(retry_result.path, source, max_attempts=3)
                            if entry.passed:
                                break

                        verification_results[nid] = entry
                        if not entry.passed:
                            logger.warning(
                                "Verification exhausted for %s — using last result anyway: %s",
                                nid, entry.reason,
                            )

        logger.info(
            "Level %d: %d nodes dispatched, %d results so far",
            level_idx, len(eligible), len(results),
        )

        # --- Exploration: check for candidates on completed nodes ---
        # Group nodes with candidates by phase
        phase_candidates: Dict[str, List[Tuple[str, Source]]] = {}
        for nid in eligible:
            if nid in results and nid not in failed_ids:
                source = source_map.get(nid)
                if source and getattr(source, "candidates", None):
                    stype = getattr(source, "type", None)
                    phase = _SOURCE_TYPE_TO_PHASE.get(stype)
                    if phase:
                        phase_candidates.setdefault(phase, []).append((nid, source))

        # Process phases in order
        for phase in _PHASE_ORDER:
            if phase not in phase_candidates:
                continue
            should_continue = await _handle_exploration_for_level(
                phase=phase,
                nodes_with_candidates=phase_candidates[phase],
                run_dir=run_dir,
                timeline=timeline,
                results=results,
                source_map=source_map,
                anon_identity_map=anon_identity_map,
                exploration_state=exploration_state,
                run_result=run_result,
            )
            if not should_continue:
                # Early return — pending exploration
                run_result.results = results
                run_result.errors = errors
                run_result.success = True
                return run_result

    # --- Timing + Fitting pass ---
    # Only run if we have results and stage includes videos/final
    layout = None
    if results and stage in ("videos", "final"):
        layout = compute_timeline_timing(timeline, results)

        # Apply fit adjustments for clips that need fitting
        fit_tasks = []
        for clip_id, clip_layout in layout.clips.items():
            if not clip_layout.needs_fit:
                continue
            if clip_id not in results:
                continue
            node_result = results[clip_id]
            if not node_result.path or not node_result.path.exists():
                continue

            fit_tasks.append(
                _apply_fit_for_clip(
                    clip_id, clip_layout, node_result, run_dir
                )
            )

        if fit_tasks:
            fit_results = await asyncio.gather(*fit_tasks, return_exceptions=True)
            for fr in fit_results:
                if isinstance(fr, Exception):
                    logger.error("Fit adjustment failed: %s", fr)
                    errors.append(f"Fit adjustment failed: {fr}")
                elif isinstance(fr, tuple):
                    cid, adjusted_path = fr
                    # Update result with adjusted path
                    old_result = results[cid]
                    results[cid] = NodeResult(
                        path=adjusted_path,
                        duration=layout.clips[cid].final_duration,
                        media_type=old_result.media_type,
                    )

    # --- Save timing.json ---
    if layout is not None:
        timing_path = run_dir / "timing.json"
        timing_data = {
            "total_duration": layout.total_duration,
            "track_order": layout.track_order,
            "clips": {
                cid: {
                    "track_id": cl.track_id,
                    "start_time": cl.start_time,
                    "raw_duration": cl.raw_duration,
                    "final_duration": cl.final_duration,
                    "fit_to": cl.fit_to,
                    "fit_method": cl.fit_method,
                    "buffer_ms": cl.buffer_ms,
                    "needs_fit": cl.needs_fit,
                    "speed_factor": (
                        round(cl.raw_duration / cl.final_duration, 4)
                        if cl.needs_fit and cl.fit_method == "speed" and cl.final_duration > 0
                        else None
                    ),
                }
                for cid, cl in layout.clips.items()
            },
        }
        timing_path.write_text(json.dumps(timing_data, indent=2))

    # --- Assembly pass ---
    has_real_failure = any(
        nid for nid in failed_ids if not nid.startswith("__anon_")
    )
    if stage == "final" and layout is not None and not has_real_failure:
        try:
            assembly_outputs = await assemble_timeline(timeline, results, layout, run_dir)
            run_result.outputs = assembly_outputs
            logger.info("Assembly complete: %s", list(assembly_outputs.keys()))
        except Exception as exc:
            logger.error("Assembly failed: %s", exc)
            errors.append(f"Assembly failed: {exc}")

    # Determine success — fail if any non-anonymous node failed/skipped
    has_real_skip = any(
        nid for nid in skipped_ids if not nid.startswith("__anon_")
    )

    run_result.results = results
    run_result.errors = errors
    run_result.success = not has_real_failure and not has_real_skip
    run_result.layout = layout

    # Write verification results if any nodes were verified
    if verification_results:
        write_verification_results(run_dir, verification_results)
        failed_verifications = [nid for nid, v in verification_results.items() if not v.passed]
        if failed_verifications:
            logger.warning(
                "Verification failed for %d node(s) (used anyway): %s",
                len(failed_verifications), ", ".join(failed_verifications),
            )

    # Mark stage complete if successful
    if run_result.success:
        mark_stage_complete(run_dir, stage)

    return run_result


# ---------------------------------------------------------------------------
# Mock mode activation
# ---------------------------------------------------------------------------

def _activate_mock_mode() -> None:
    """Enable mock mode for all generation backends."""
    from shared.replicate_client import set_mock_mode
    from generation import batch_img, batch_vid, gpt_image2, nano_banana2

    set_mock_mode(True)
    batch_img.MOCK_REPLICATE = True
    batch_vid.MOCK_REPLICATE = True
    gpt_image2.MOCK_REPLICATE = True
    nano_banana2.MOCK_GENERATE = True


def _deactivate_mock_mode() -> None:
    """Disable mock mode for all generation backends."""
    from shared.replicate_client import set_mock_mode
    from generation import batch_img, batch_vid, gpt_image2, nano_banana2

    set_mock_mode(False)
    batch_img.MOCK_REPLICATE = False
    batch_vid.MOCK_REPLICATE = False
    gpt_image2.MOCK_REPLICATE = False
    nano_banana2.MOCK_GENERATE = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_timeline(
    timeline: Timeline,
    run_dir: Path,
    stage: str = "final",
    mock: bool = False,
    concurrency: Optional[Dict[str, int]] = None,
    resume: bool = False,
    timeline_dir: Optional[Path] = None,
    exploration_state: Optional[ExplorationState] = None,
) -> RunResult:
    """Execute a timeline by walking its dependency DAG.

    This is the synchronous entry point — calls ``asyncio.run()`` internally.
    Must NOT be called from inside a running event loop.

    Args:
        timeline: Parsed Timeline object.
        run_dir: Directory for all output files.
        stage: Execution stage — ``"images"``, ``"videos"``, or ``"final"``.
        mock: If True, activate mock mode (no real API calls).
        concurrency: Per-type concurrency limits, e.g. ``{"image": 4, "video": 3}``.
        resume: If True, skip already-completed stages and reuse existing outputs.
        timeline_dir: Directory containing the timeline file (for FileSource resolution).
        exploration_state: Optional ExplorationState for Cloud Run pause/resume flow.

    Returns:
        RunResult with all completed node results and error information.
    """
    # Defense-in-depth: validate timeline before execution
    validation_result = validate(timeline, timeline_dir=timeline_dir)
    if not validation_result.is_valid:
        error_msgs = [f"{e.severity}: {e.message}" for e in validation_result.errors]
        raise ValueError(f"Timeline validation failed:\n" + "\n".join(error_msgs))

    if mock:
        _activate_mock_mode()

    try:
        return asyncio.run(
            _execute_async(
                timeline=timeline,
                run_dir=run_dir,
                stage=stage,
                concurrency=concurrency,
                resume=resume,
                timeline_dir=timeline_dir,
                exploration_state=exploration_state,
            )
        )
    finally:
        if mock:
            _deactivate_mock_mode()
