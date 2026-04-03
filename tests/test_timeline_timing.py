"""Tests for timeline timing computation."""

from pathlib import Path

import pytest

from timeline.model import (
    Clip,
    FileSource,
    ImageSource,
    NodeResult,
    SilenceSource,
    StillSource,
    Timeline,
    Track,
    TTSSource,
    VideoSource,
)
from timeline.timing import ClipLayout, TimelineLayout, compute_timeline_timing


def _make_timeline(tracks: list[Track]) -> Timeline:
    return Timeline(tracks=tracks)


def _nr(duration: float | None = None, media_type: str = "audio") -> NodeResult:
    return NodeResult(path=Path("/tmp/fake.wav"), duration=duration, media_type=media_type)


# ---------------------------------------------------------------------------
# 1. Sequential placement (3 clips, check start_times)
# ---------------------------------------------------------------------------


def test_sequential_placement_three_clips():
    track = Track(id="v", type="video", clips=[
        Clip(id="a", source=VideoSource(duration=3)),
        Clip(id="b", source=VideoSource(duration=5)),
        Clip(id="c", source=VideoSource(duration=2)),
    ])
    layout = compute_timeline_timing(_make_timeline([track]), {})
    assert layout.clips["a"].start_time == pytest.approx(0.0)
    assert layout.clips["b"].start_time == pytest.approx(3.0)
    assert layout.clips["c"].start_time == pytest.approx(8.0)
    assert layout.total_duration == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 2. Explicit start_time overrides sequential
# ---------------------------------------------------------------------------


def test_explicit_start_time_overrides():
    track = Track(id="v", type="video", clips=[
        Clip(id="a", source=VideoSource(duration=3)),
        Clip(id="b", source=VideoSource(duration=5), start_time=10.0),
        Clip(id="c", source=VideoSource(duration=2)),
    ])
    layout = compute_timeline_timing(_make_timeline([track]), {})
    assert layout.clips["a"].start_time == pytest.approx(0.0)
    assert layout.clips["b"].start_time == pytest.approx(10.0)
    assert layout.clips["c"].start_time == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# 3. fit_to basic: narration clip fits to video clip duration
# ---------------------------------------------------------------------------


def test_fit_to_basic():
    tracks = [
        Track(id="v", type="video", clips=[
            Clip(id="vid1", source=VideoSource(duration=8)),
        ]),
        Track(id="n", type="narration", clips=[
            Clip(id="nar1", source=TTSSource(text="hello"), fit_to="vid1"),
        ]),
    ]
    results = {"nar1": _nr(duration=5.0)}
    layout = compute_timeline_timing(_make_timeline(tracks), results)
    assert layout.clips["nar1"].final_duration == pytest.approx(8.0)
    assert layout.clips["nar1"].raw_duration == pytest.approx(5.0)
    assert layout.clips["nar1"].needs_fit is True


# ---------------------------------------------------------------------------
# 4. fit_to chain: A→B→C resolves in correct order
# ---------------------------------------------------------------------------


def test_fit_to_chain():
    tracks = [
        Track(id="v", type="video", clips=[
            Clip(id="c", source=VideoSource(duration=10)),
        ]),
        Track(id="n1", type="narration", clips=[
            Clip(id="b", source=TTSSource(text="b"), fit_to="c"),
        ]),
        Track(id="n2", type="audio", clips=[
            Clip(id="a", source=TTSSource(text="a"), fit_to="b"),
        ]),
    ]
    results = {"b": _nr(duration=4.0), "a": _nr(duration=2.0)}
    layout = compute_timeline_timing(_make_timeline(tracks), results)
    # C has duration 10, B fits to C → 10, A fits to B → 10
    assert layout.clips["b"].final_duration == pytest.approx(10.0)
    assert layout.clips["a"].final_duration == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 5. fit_to with buffer_ms (positive and negative)
# ---------------------------------------------------------------------------


def test_fit_to_positive_buffer():
    """buffer_ms is applied to raw_duration, not the target (REQ-TIME-009)."""
    tracks = [
        Track(id="v", type="video", clips=[
            Clip(id="vid", source=VideoSource(duration=6)),
        ]),
        Track(id="n", type="narration", clips=[
            Clip(id="nar", source=TTSSource(text="x"), fit_to="vid", buffer_ms=500),
        ]),
    ]
    results = {"nar": _nr(duration=3.0)}
    layout = compute_timeline_timing(_make_timeline(tracks), results)
    # raw_duration = 3.0 + 0.5 = 3.5 (buffer applied to raw)
    assert layout.clips["nar"].raw_duration == pytest.approx(3.5)
    # final_duration = target duration (6.0), not target + buffer
    assert layout.clips["nar"].final_duration == pytest.approx(6.0)


def test_fit_to_negative_buffer():
    """Negative buffer_ms reduces raw_duration (REQ-TIME-009)."""
    tracks = [
        Track(id="v", type="video", clips=[
            Clip(id="vid", source=VideoSource(duration=6)),
        ]),
        Track(id="n", type="narration", clips=[
            Clip(id="nar", source=TTSSource(text="x"), fit_to="vid", buffer_ms=-200),
        ]),
    ]
    results = {"nar": _nr(duration=3.0)}
    layout = compute_timeline_timing(_make_timeline(tracks), results)
    # raw_duration = 3.0 - 0.2 = 2.8 (buffer applied to raw)
    assert layout.clips["nar"].raw_duration == pytest.approx(2.8)
    # final_duration = target duration (6.0), not target - buffer
    assert layout.clips["nar"].final_duration == pytest.approx(6.0)


def test_buffer_ms_applied_to_raw_without_fit_to():
    """buffer_ms pads raw_duration even without fit_to (REQ-TIME-009)."""
    tracks = [
        Track(id="n", type="narration", clips=[
            Clip(id="nar", source=TTSSource(text="x"), buffer_ms=500),
        ]),
    ]
    results = {"nar": _nr(duration=3.0)}
    layout = compute_timeline_timing(_make_timeline(tracks), results)
    assert layout.clips["nar"].raw_duration == pytest.approx(3.5)
    assert layout.clips["nar"].final_duration == pytest.approx(3.5)


def test_buffer_ms_on_target_of_fit_to():
    """When a clip with buffer_ms is the TARGET of a fit_to, its effective
    duration (raw + buffer) is what the fitting clip matches."""
    tracks = [
        Track(id="n", type="narration", clips=[
            Clip(id="nar", source=TTSSource(text="x"), buffer_ms=500),
        ]),
        Track(id="v", type="video", clips=[
            Clip(id="vid", source=VideoSource(duration=10), fit_to="nar"),
        ]),
    ]
    results = {"nar": _nr(duration=3.0)}
    layout = compute_timeline_timing(_make_timeline(tracks), results)
    # nar raw_duration = 3.0 + 0.5 = 3.5
    assert layout.clips["nar"].final_duration == pytest.approx(3.5)
    # vid fits to nar, so vid gets nar's final_duration (3.5)
    assert layout.clips["vid"].final_duration == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# 6. fit_to with negative start_time (relative offset)
# ---------------------------------------------------------------------------


def test_fit_to_negative_start_time():
    tracks = [
        Track(id="v", type="video", clips=[
            Clip(id="vid", source=VideoSource(duration=6), start_time=5.0),
        ]),
        Track(id="n", type="narration", clips=[
            Clip(id="nar", source=TTSSource(text="x"), fit_to="vid", start_time=-1.0),
        ]),
    ]
    results = {"nar": _nr(duration=3.0)}
    layout = compute_timeline_timing(_make_timeline(tracks), results)
    # target start_time=5.0, clip start_time=-1.0 → 5.0 + (-1.0) = 4.0
    assert layout.clips["nar"].start_time == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# 7. fit_to start_time alignment (no explicit start_time)
# ---------------------------------------------------------------------------


def test_fit_to_start_alignment():
    tracks = [
        Track(id="v", type="video", clips=[
            Clip(id="v1", source=VideoSource(duration=3)),
            Clip(id="v2", source=VideoSource(duration=5)),
        ]),
        Track(id="n", type="narration", clips=[
            Clip(id="nar", source=TTSSource(text="x"), fit_to="v2"),
        ]),
    ]
    results = {"nar": _nr(duration=2.0)}
    layout = compute_timeline_timing(_make_timeline(tracks), results)
    # v2 starts at 3.0, nar should align to 3.0
    assert layout.clips["nar"].start_time == pytest.approx(3.0)
    assert layout.clips["nar"].final_duration == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# 8. Multi-clip fitting: 2 clips fit_to same target, proportional
# ---------------------------------------------------------------------------


def test_multi_clip_fitting_two_clips():
    tracks = [
        Track(id="v", type="video", clips=[
            Clip(id="vid", source=VideoSource(duration=6)),
        ]),
        Track(id="n", type="narration", clips=[
            Clip(id="n1", source=TTSSource(text="a"), fit_to="vid"),
            Clip(id="n2", source=TTSSource(text="b"), fit_to="vid"),
        ]),
    ]
    # Raw durations: n1=3s, n2=6s, total=9s, target=6s
    # n1 gets 3/9 * 6 = 2s, n2 gets 6/9 * 6 = 4s
    results = {"n1": _nr(duration=3.0), "n2": _nr(duration=6.0)}
    layout = compute_timeline_timing(_make_timeline(tracks), results)
    assert layout.clips["n1"].final_duration == pytest.approx(2.0)
    assert layout.clips["n2"].final_duration == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# 9. Multi-clip fitting: 3 clips, verify proportions
# ---------------------------------------------------------------------------


def test_multi_clip_fitting_three_clips():
    tracks = [
        Track(id="v", type="video", clips=[
            Clip(id="vid", source=VideoSource(duration=12)),
        ]),
        Track(id="n", type="narration", clips=[
            Clip(id="n1", source=TTSSource(text="a"), fit_to="vid"),
            Clip(id="n2", source=TTSSource(text="b"), fit_to="vid"),
            Clip(id="n3", source=TTSSource(text="c"), fit_to="vid"),
        ]),
    ]
    # Raw: n1=2, n2=4, n3=6, total=12, target=12
    # n1: 2/12*12=2, n2: 4/12*12=4, n3: 6/12*12=6
    results = {"n1": _nr(duration=2.0), "n2": _nr(duration=4.0), "n3": _nr(duration=6.0)}
    layout = compute_timeline_timing(_make_timeline(tracks), results)
    assert layout.clips["n1"].final_duration == pytest.approx(2.0)
    assert layout.clips["n2"].final_duration == pytest.approx(4.0)
    assert layout.clips["n3"].final_duration == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# 10. Duration from VideoSource.duration field
# ---------------------------------------------------------------------------


def test_duration_from_video_source():
    track = Track(id="v", type="video", clips=[
        Clip(id="vid", source=VideoSource(duration=7)),
    ])
    layout = compute_timeline_timing(_make_timeline([track]), {})
    assert layout.clips["vid"].raw_duration == pytest.approx(7.0)
    assert layout.clips["vid"].final_duration == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# 11. Duration from SilenceSource.duration field
# ---------------------------------------------------------------------------


def test_duration_from_silence_source():
    track = Track(id="a", type="audio", clips=[
        Clip(id="sil", source=SilenceSource(duration=2.5)),
    ])
    layout = compute_timeline_timing(_make_timeline([track]), {})
    assert layout.clips["sil"].raw_duration == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# 12. Duration from FileSource start/end
# ---------------------------------------------------------------------------


def test_duration_from_file_source_start_end():
    track = Track(id="a", type="audio", clips=[
        Clip(id="f", source=FileSource(path="/tmp/x.mp3", start=1.0, end=4.5)),
    ])
    layout = compute_timeline_timing(_make_timeline([track]), {})
    assert layout.clips["f"].raw_duration == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# 13. Duration "auto" resolves from NodeResult
# ---------------------------------------------------------------------------


def test_duration_auto_from_node_result():
    track = Track(id="n", type="narration", clips=[
        Clip(id="nar", source=TTSSource(text="hello"), duration="auto"),
    ])
    results = {"nar": _nr(duration=4.2)}
    layout = compute_timeline_timing(_make_timeline([track]), results)
    assert layout.clips["nar"].raw_duration == pytest.approx(4.2)


# ---------------------------------------------------------------------------
# 14. Image source duration is 0
# ---------------------------------------------------------------------------


def test_image_source_duration_zero():
    track = Track(id="i", type="video", clips=[
        Clip(id="img", source=ImageSource(prompt="a cat")),
    ])
    layout = compute_timeline_timing(_make_timeline([track]), {})
    assert layout.clips["img"].raw_duration == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 15. Cycle in fit_to sub-DAG raises error
# ---------------------------------------------------------------------------


def test_cycle_raises_error():
    tracks = [
        Track(id="t1", type="video", clips=[
            Clip(id="a", source=VideoSource(duration=5), fit_to="b"),
        ]),
        Track(id="t2", type="narration", clips=[
            Clip(id="b", source=TTSSource(text="x"), fit_to="a"),
        ]),
    ]
    results = {"b": _nr(duration=3.0)}
    with pytest.raises(ValueError, match="Cycle"):
        compute_timeline_timing(_make_timeline(tracks), results)


# ---------------------------------------------------------------------------
# 16. fit_to referencing non-existent clip raises error
# ---------------------------------------------------------------------------


def test_fit_to_nonexistent_raises():
    tracks = [
        Track(id="n", type="narration", clips=[
            Clip(id="nar", source=TTSSource(text="x"), fit_to="ghost"),
        ]),
    ]
    results = {"nar": _nr(duration=3.0)}
    with pytest.raises(ValueError, match="does not exist"):
        compute_timeline_timing(_make_timeline(tracks), results)


# ---------------------------------------------------------------------------
# 17. Empty timeline produces empty layout
# ---------------------------------------------------------------------------


def test_empty_timeline():
    layout = compute_timeline_timing(Timeline(), {})
    assert layout.clips == {}
    assert layout.track_order == []
    assert layout.total_duration == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 18. Track with single clip, no fit_to
# ---------------------------------------------------------------------------


def test_single_clip_no_fit():
    track = Track(id="v", type="video", clips=[
        Clip(id="vid", source=VideoSource(duration=4)),
    ])
    layout = compute_timeline_timing(_make_timeline([track]), {})
    assert layout.clips["vid"].start_time == pytest.approx(0.0)
    assert layout.clips["vid"].final_duration == pytest.approx(4.0)
    assert layout.total_duration == pytest.approx(4.0)
    assert layout.clips["vid"].needs_fit is False


# ---------------------------------------------------------------------------
# 19. Mixed tracks: video + narration with fit_to between them
# ---------------------------------------------------------------------------


def test_mixed_tracks_with_fit():
    tracks = [
        Track(id="v", type="video", clips=[
            Clip(id="v1", source=VideoSource(duration=4)),
            Clip(id="v2", source=VideoSource(duration=6)),
        ]),
        Track(id="n", type="narration", clips=[
            Clip(id="n1", source=TTSSource(text="first"), fit_to="v1"),
            Clip(id="n2", source=TTSSource(text="second"), fit_to="v2"),
        ]),
    ]
    results = {"n1": _nr(duration=3.0), "n2": _nr(duration=5.0)}
    layout = compute_timeline_timing(_make_timeline(tracks), results)

    # n1 fits to v1 (4s), n2 fits to v2 (6s)
    assert layout.clips["n1"].final_duration == pytest.approx(4.0)
    assert layout.clips["n2"].final_duration == pytest.approx(6.0)
    # n1 aligns to v1 start (0), n2 aligns to v2 start (4)
    assert layout.clips["n1"].start_time == pytest.approx(0.0)
    assert layout.clips["n2"].start_time == pytest.approx(4.0)
    assert layout.total_duration == pytest.approx(10.0)
