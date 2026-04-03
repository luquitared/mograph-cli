"""Tests for timeline DAG construction and analysis."""

import pytest

from timeline.dag import (
    DAG, DAGNode, build_dag, build_dag_with_identity_map, build_timing_dag,
    detect_cycles, topological_sort, topological_sort_nodes,
)
from timeline.model import (
    Clip,
    Generate,
    ImageSource,
    Project,
    Ref,
    StillSource,
    Timeline,
    Track,
    VideoSource,
)


def _make_timeline(tracks=None, assets=None):
    """Helper to build a minimal valid timeline."""
    return Timeline(
        version=1,
        project=Project(name="test"),
        tracks=tracks or [],
        assets=assets or {},
    )


class TestBuildDag:
    def test_simple_acyclic(self):
        """Asset -> clip dependency creates correct nodes and edges."""
        tl = _make_timeline(
            assets={"img1": ImageSource(prompt="test")},
            tracks=[Track(id="v", type="video", clips=[
                Clip(id="vid1", source=VideoSource(
                    prompt="test",
                    first_frame=Ref(ref="img1"),
                )),
            ])],
        )
        dag = build_dag(tl)
        assert "img1" in dag.nodes
        assert "vid1" in dag.nodes
        assert dag.nodes["img1"].node_type == "asset"
        assert dag.nodes["vid1"].node_type == "clip"
        assert ("vid1", "img1") in dag.edges

    def test_ref_edge_direction(self):
        """Edge goes from dependent to dependency."""
        tl = _make_timeline(
            assets={"bg": ImageSource(prompt="bg")},
            tracks=[Track(id="v", type="video", clips=[
                Clip(id="c1", source=VideoSource(prompt="test", first_frame=Ref(ref="bg"))),
            ])],
        )
        dag = build_dag(tl)
        # c1 depends on bg
        assert ("c1", "bg") in dag.edges
        assert ("bg", "c1") not in dag.edges

    def test_generate_creates_anonymous_node(self):
        """Generate sources create anonymous nodes with edges."""
        gen = Generate(generate=ImageSource(prompt="inline"))
        tl = _make_timeline(tracks=[Track(id="v", type="video", clips=[
            Clip(id="vid1", source=VideoSource(
                prompt="test",
                first_frame=gen,
            )),
        ])])
        dag = build_dag(tl)
        assert "vid1" in dag.nodes
        anon_nodes = [n for n in dag.nodes if n.startswith("__anon_")]
        assert len(anon_nodes) == 1
        assert ("vid1", anon_nodes[0]) in dag.edges

    def test_generate_identity_map(self):
        """build_dag_with_identity_map returns correct anon_id mapping."""
        gen = Generate(generate=ImageSource(prompt="inline"))
        tl = _make_timeline(tracks=[Track(id="v", type="video", clips=[
            Clip(id="vid1", source=VideoSource(
                prompt="test",
                first_frame=gen,
            )),
        ])])
        dag, identity_map = build_dag_with_identity_map(tl)
        anon_nodes = [n for n in dag.nodes if n.startswith("__anon_")]
        assert len(anon_nodes) == 1
        assert id(gen) in identity_map
        assert identity_map[id(gen)] == anon_nodes[0]

    def test_fit_to_edge(self):
        """fit_to creates dependency edges."""
        tl = _make_timeline(tracks=[Track(id="v", type="video", clips=[
            Clip(id="c1", source=VideoSource(prompt="test")),
            Clip(id="c2", source=VideoSource(prompt="test"), fit_to="c1"),
        ])])
        dag = build_dag(tl)
        assert ("c2", "c1") in dag.edges

    def test_still_ref_edge(self):
        """StillSource with Ref image creates edge."""
        tl = _make_timeline(
            assets={"img1": ImageSource(prompt="test")},
            tracks=[Track(id="v", type="video", clips=[
                Clip(id="s1", source=StillSource(image=Ref(ref="img1"), duration=3.0)),
            ])],
        )
        dag = build_dag(tl)
        assert ("s1", "img1") in dag.edges

    def test_no_dependency_timeline(self):
        """Timeline with no refs/fit_to has nodes but no edges."""
        tl = _make_timeline(tracks=[Track(id="v", type="video", clips=[
            Clip(id="c1", source=VideoSource(prompt="a")),
            Clip(id="c2", source=VideoSource(prompt="b")),
        ])])
        dag = build_dag(tl)
        assert len(dag.nodes) == 2
        assert len(dag.edges) == 0


class TestDetectCycles:
    def test_no_cycle(self):
        """Acyclic graph returns empty list."""
        dag = DAG(
            nodes={"a": DAGNode("a", "clip"), "b": DAGNode("b", "clip", ["a"])},
            edges=[("b", "a")],
        )
        assert detect_cycles(dag) == []

    def test_simple_cycle(self):
        """Two-node cycle is detected."""
        dag = DAG(
            nodes={
                "a": DAGNode("a", "clip", ["b"]),
                "b": DAGNode("b", "clip", ["a"]),
            },
            edges=[("a", "b"), ("b", "a")],
        )
        cycles = detect_cycles(dag)
        assert len(cycles) > 0
        # At least one cycle should contain both a and b
        found = any("a" in c and "b" in c for c in cycles)
        assert found

    def test_three_node_cycle(self):
        """Three-node cycle is detected."""
        dag = DAG(
            nodes={
                "a": DAGNode("a", "clip", ["b"]),
                "b": DAGNode("b", "clip", ["c"]),
                "c": DAGNode("c", "clip", ["a"]),
            },
            edges=[("a", "b"), ("b", "c"), ("c", "a")],
        )
        cycles = detect_cycles(dag)
        assert len(cycles) > 0


class TestTopologicalSort:
    def test_independent_nodes_same_level(self):
        """Nodes with no dependencies are all at level 0."""
        dag = DAG(nodes={
            "a": DAGNode("a", "clip"),
            "b": DAGNode("b", "clip"),
            "c": DAGNode("c", "clip"),
        }, edges=[])
        levels = topological_sort(dag)
        assert len(levels) == 1
        assert set(levels[0]) == {"a", "b", "c"}

    def test_linear_chain(self):
        """Linear chain produces one node per level."""
        dag = DAG(
            nodes={
                "a": DAGNode("a", "clip"),
                "b": DAGNode("b", "clip", ["a"]),
                "c": DAGNode("c", "clip", ["b"]),
            },
            edges=[("b", "a"), ("c", "b")],
        )
        levels = topological_sort(dag)
        assert len(levels) == 3
        assert levels[0] == ["a"]
        assert levels[1] == ["b"]
        assert levels[2] == ["c"]

    def test_diamond_dependency(self):
        """Diamond dependency: d depends on b,c; both depend on a."""
        dag = DAG(
            nodes={
                "a": DAGNode("a", "asset"),
                "b": DAGNode("b", "clip", ["a"]),
                "c": DAGNode("c", "clip", ["a"]),
                "d": DAGNode("d", "clip", ["b", "c"]),
            },
            edges=[("b", "a"), ("c", "a"), ("d", "b"), ("d", "c")],
        )
        levels = topological_sort(dag)
        assert levels[0] == ["a"]
        assert set(levels[1]) == {"b", "c"}
        assert levels[2] == ["d"]

    def test_empty_dag(self):
        """Empty DAG returns empty levels."""
        dag = DAG()
        levels = topological_sort(dag)
        assert levels == []


class TestTopologicalSortNodes:
    def test_basic(self):
        """topological_sort_nodes produces correct levels."""
        levels = topological_sort_nodes(
            ["a", "b", "c"],
            [("b", "a"), ("c", "b")],
        )
        assert len(levels) == 3
        assert levels[0] == ["a"]
        assert levels[1] == ["b"]
        assert levels[2] == ["c"]

    def test_empty(self):
        """Empty inputs produce empty levels."""
        levels = topological_sort_nodes([], [])
        assert levels == []

    def test_independent_nodes(self):
        """Nodes with no edges are all at level 0."""
        levels = topological_sort_nodes(["x", "y", "z"], [])
        assert len(levels) == 1
        assert set(levels[0]) == {"x", "y", "z"}


class TestBuildTimingDag:
    def test_only_fit_to_edges(self):
        """Timing DAG ignores ref edges, only includes fit_to."""
        tl = _make_timeline(
            assets={"img1": ImageSource(prompt="test")},
            tracks=[Track(id="v", type="video", clips=[
                Clip(id="c1", source=VideoSource(prompt="a", first_frame=Ref(ref="img1"))),
                Clip(id="c2", source=VideoSource(prompt="b"), fit_to="c1"),
            ])],
        )
        dag = build_timing_dag(tl)
        # Only fit_to edge, not the ref edge
        assert ("c2", "c1") in dag.edges
        assert len(dag.edges) == 1

    def test_timing_cycle_detected(self):
        """Mutual fit_to creates a cycle in timing DAG."""
        tl = _make_timeline(tracks=[Track(id="v", type="video", clips=[
            Clip(id="a", source=VideoSource(prompt="a"), fit_to="b"),
            Clip(id="b", source=VideoSource(prompt="b"), fit_to="a"),
        ])])
        dag = build_timing_dag(tl)
        cycles = detect_cycles(dag)
        assert len(cycles) > 0
