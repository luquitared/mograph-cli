"""DAG construction and analysis for timeline dependency graphs.

Builds directed acyclic graphs from ref, generate, and fit_to references
in timelines. Provides cycle detection and topological sorting for
execution scheduling.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from timeline.model import (
    Clip,
    FileSource,
    Generate,
    ImageSource,
    Ref,
    SilenceSource,
    Source,
    StillSource,
    TTSSource,
    Timeline,
    Track,
    VideoSource,
)


@dataclass
class DAGNode:
    """A node in the dependency graph."""
    id: str
    node_type: str  # "clip" or "asset"
    dependencies: List[str] = field(default_factory=list)


@dataclass
class DAG:
    """Directed acyclic graph of timeline dependencies."""
    nodes: Dict[str, DAGNode] = field(default_factory=dict)
    edges: List[Tuple[str, str]] = field(default_factory=list)  # (from, to) = "from depends on to"


def build_dag(timeline: Timeline) -> DAG:
    """Build a full dependency DAG from a timeline.

    Creates nodes for every clip and asset, then adds edges for:
    - ref references in first_frame, last_frame, still image
    - generate inline sources (creates anonymous nodes)
    - fit_to references
    """
    dag, _ = build_dag_with_identity_map(timeline)
    return dag


def build_dag_with_identity_map(timeline: Timeline) -> Tuple[DAG, Dict[int, str]]:
    """Build a full dependency DAG and an anonymous node identity map.

    Like build_dag(), but also returns a mapping of id(frame_input) -> anon_id
    for anonymous Generate nodes — used by the executor to resolve frame inputs
    without duplicating the traversal.
    """
    dag = DAG()
    _anon_counter = [0]
    anon_identity_map: Dict[int, str] = {}

    # Add asset nodes
    for asset_id in timeline.assets:
        dag.nodes[asset_id] = DAGNode(id=asset_id, node_type="asset")

    # Add clip nodes
    for track in timeline.tracks:
        for clip in track.clips:
            if clip.id:
                dag.nodes[clip.id] = DAGNode(id=clip.id, node_type="clip")

    # Process assets for refs within their sources
    for asset_id, source in timeline.assets.items():
        _extract_source_deps(dag, asset_id, source, _anon_counter, anon_identity_map)

    # Process clips
    for track in timeline.tracks:
        for clip in track.clips:
            if not clip.id:
                continue
            # Source-level deps
            if clip.source:
                _extract_source_deps(dag, clip.id, clip.source, _anon_counter, anon_identity_map)
            # fit_to dep
            if clip.fit_to:
                _add_edge(dag, clip.id, clip.fit_to)

    return dag, anon_identity_map


def _extract_source_deps(
    dag: DAG, owner_id: str, source: Source, anon_counter: List[int],
    anon_identity_map: Dict[int, str],
) -> None:
    """Extract dependency edges from a source's fields."""
    if isinstance(source, ImageSource):
        for item in source.reference_images:
            if isinstance(item, Ref):
                _add_edge(dag, owner_id, item.ref)
    elif isinstance(source, VideoSource):
        _process_frame_input(dag, owner_id, source.first_frame, anon_counter, anon_identity_map)
        _process_frame_input(dag, owner_id, source.last_frame, anon_counter, anon_identity_map)
        # reference_images with Ref entries
        for item in source.reference_images:
            if isinstance(item, Ref):
                _add_edge(dag, owner_id, item.ref)
        # reference_videos with Ref entries (video-to-video chaining)
        for item in source.reference_videos:
            if isinstance(item, Ref):
                _add_edge(dag, owner_id, item.ref)
    elif isinstance(source, StillSource):
        if isinstance(source.image, Ref):
            _add_edge(dag, owner_id, source.image.ref)


def _process_frame_input(
    dag: DAG, owner_id: str, frame_input, anon_counter: List[int],
    anon_identity_map: Dict[int, str],
) -> None:
    """Process a first_frame or last_frame value for dependencies."""
    if frame_input is None or isinstance(frame_input, str):
        return
    if isinstance(frame_input, Ref):
        _add_edge(dag, owner_id, frame_input.ref)
    elif isinstance(frame_input, Generate):
        if frame_input.generate is not None:
            anon_id = f"__anon_{anon_counter[0]}"
            anon_counter[0] += 1
            dag.nodes[anon_id] = DAGNode(id=anon_id, node_type="asset")
            anon_identity_map[id(frame_input)] = anon_id
            _add_edge(dag, owner_id, anon_id)
            # Recurse into the generated source
            _extract_source_deps(dag, anon_id, frame_input.generate, anon_counter, anon_identity_map)


def _add_edge(dag: DAG, from_id: str, to_id: str) -> None:
    """Add a dependency edge: from_id depends on to_id."""
    dag.edges.append((from_id, to_id))
    if from_id in dag.nodes:
        dag.nodes[from_id].dependencies.append(to_id)


def detect_cycles(dag: DAG) -> List[List[str]]:
    """Detect cycles in the DAG using DFS.

    Returns a list of cycles, where each cycle is a list of node IDs.
    """
    # Build adjacency list
    adj: Dict[str, List[str]] = defaultdict(list)
    for from_id, to_id in dag.edges:
        adj[from_id].append(to_id)

    visited: Set[str] = set()
    rec_stack: Set[str] = set()
    path: List[str] = []
    cycles: List[List[str]] = []

    def dfs(node: str) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                # Found a cycle — extract it from path
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)

        path.pop()
        rec_stack.discard(node)

    for node_id in dag.nodes:
        if node_id not in visited:
            dfs(node_id)

    return cycles


def topological_sort_nodes(
    node_ids: List[str], edges: List[Tuple[str, str]]
) -> List[List[str]]:
    """Topological sort returning execution levels.

    Standalone function that takes node IDs and edges directly.

    Args:
        node_ids: List of all node IDs.
        edges: List of (from_id, to_id) meaning "from depends on to".

    Returns:
        List of levels, where each level is a list of node IDs that can
        execute in parallel. Level 0 = leaf nodes (no dependencies).
    """
    node_set = set(node_ids)
    in_degree: Dict[str, int] = {nid: 0 for nid in node_ids}
    dependents: Dict[str, List[str]] = defaultdict(list)

    for from_id, to_id in edges:
        if from_id in node_set and to_id in node_set:
            in_degree[from_id] = in_degree.get(from_id, 0) + 1
            dependents[to_id].append(from_id)

    levels: List[List[str]] = []
    queue = deque([nid for nid, deg in in_degree.items() if deg == 0])

    while queue:
        level = list(queue)
        levels.append(level)
        next_queue: deque = deque()
        for node_id in level:
            for dependent in dependents.get(node_id, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_queue.append(dependent)
        queue = next_queue

    return levels


def topological_sort(dag: DAG) -> List[List[str]]:
    """Topological sort returning execution levels.

    Level 0 = leaf nodes (no dependencies).
    Level N = nodes whose dependencies are all in levels < N.
    Nodes at the same level can execute in parallel.
    """
    return topological_sort_nodes(list(dag.nodes.keys()), dag.edges)


def build_timing_dag(timeline: Timeline) -> DAG:
    """Build a DAG containing only fit_to relationships.

    Used to detect timing cycles (e.g., A fit_to B and B fit_to A).
    """
    dag = DAG()

    for track in timeline.tracks:
        for clip in track.clips:
            if clip.id:
                dag.nodes[clip.id] = DAGNode(id=clip.id, node_type="clip")

    for track in timeline.tracks:
        for clip in track.clips:
            if clip.id and clip.fit_to:
                _add_edge(dag, clip.id, clip.fit_to)

    return dag
