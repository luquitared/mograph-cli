"""Tests for exploration/candidates integration in the timeline executor."""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from timeline.model import (
    Clip,
    Defaults,
    ImageSource,
    NodeResult,
    Project,
    TTSSource,
    Timeline,
    Track,
    VideoSource,
)
from timeline.executor import RunResult, execute_timeline
from timeline.explorer import (
    ExplorationState,
    read_manifest,
    read_selections,
    write_selections,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_timeline(**kwargs) -> Timeline:
    """Build a Timeline with sensible defaults, overriding with kwargs."""
    return Timeline(
        version=1,
        project=kwargs.get("project", Project(name="test")),
        defaults=kwargs.get("defaults", Defaults()),
        assets=kwargs.get("assets", {}),
        tracks=kwargs.get("tracks", []),
    )


@pytest.fixture(autouse=True)
def _ensure_api_keys(monkeypatch):
    """Set dummy API keys so mock mode doesn't fail on missing tokens."""
    if not os.environ.get("GOOGLE_API_KEY"):
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key-for-mock")
    if not os.environ.get("REPLICATE_API_TOKEN"):
        monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token-for-mock")


# ---------------------------------------------------------------------------
# Test: candidates on ImageSource triggers candidate generation
# ---------------------------------------------------------------------------

class TestCandidateGeneration:
    def test_image_candidates_triggers_generation(self, tmp_path):
        """An ImageSource with candidates generates variant outputs."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(
                        id="img1",
                        source=ImageSource(
                            prompt="a hero shot",
                            candidates=[
                                {"prompt": "alt hero 1"},
                                {"prompt": "alt hero 2"},
                            ],
                            select=1,
                        ),
                    ),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="images", mock=True)

        # Should pause for exploration (no selections file, CLI mode)
        assert result.pending_exploration == "images"
        # Default image should still be generated
        assert "img1" in result.results
        # Candidate variants should also be generated
        assert "img1_candidate_1" in result.results
        assert "img1_candidate_2" in result.results

    def test_tts_candidates_triggers_generation(self, tmp_path):
        """A TTSSource with candidates generates variant outputs."""
        tl = _make_timeline(
            tracks=[
                Track(id="narration", type="narration", clips=[
                    Clip(
                        id="tts1",
                        source=TTSSource(
                            text="Hello world",
                            candidates=[
                                {"voice": "Puck"},
                                {"voice": "Charon"},
                            ],
                            select=1,
                        ),
                    ),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="images", mock=True)

        assert result.pending_exploration == "tts"
        assert "tts1" in result.results
        assert "tts1_candidate_1" in result.results
        assert "tts1_candidate_2" in result.results


# ---------------------------------------------------------------------------
# Test: SelectionManifest is written after candidate generation
# ---------------------------------------------------------------------------

class TestManifestWritten:
    def test_manifest_written_for_image_candidates(self, tmp_path):
        """After generating candidates, a selection manifest is written to disk."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(
                        id="img1",
                        source=ImageSource(
                            prompt="a hero shot",
                            candidates=[{"prompt": "alt 1"}],
                            select=1,
                        ),
                    ),
                ]),
            ],
        )

        execute_timeline(tl, tmp_path, stage="images", mock=True)

        manifest = read_manifest(tmp_path, "images")
        assert manifest is not None
        assert manifest.phase == "images"
        assert len(manifest.pending_selections) == 1
        ps = manifest.pending_selections[0]
        assert ps.id == "img1"
        assert ps.select == 1
        # Should have default (0) + 1 candidate
        assert len(ps.candidates) == 2
        assert ps.candidates[0].index == 0
        assert ps.candidates[1].index == 1


# ---------------------------------------------------------------------------
# Test: pending_exploration set when no ExplorationState and no selections
# ---------------------------------------------------------------------------

class TestPendingExploration:
    def test_pending_exploration_set_in_cli_mode(self, tmp_path):
        """In CLI mode (no ExplorationState), pending_exploration is set
        when candidates exist but no selections file."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(
                        id="img1",
                        source=ImageSource(
                            prompt="test",
                            candidates=[{"prompt": "alt"}],
                        ),
                    ),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="images", mock=True)

        assert result.pending_exploration == "images"
        assert result.success is True  # not treated as failure

    def test_no_pending_when_no_candidates(self, tmp_path):
        """Without candidates, pending_exploration stays None."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(id="img1", source=ImageSource(prompt="test")),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="images", mock=True)

        assert result.pending_exploration is None
        assert result.success is True


# ---------------------------------------------------------------------------
# Test: existing selections file is applied on resume
# ---------------------------------------------------------------------------

class TestSelectionsAppliedOnResume:
    def test_selections_applied_on_resume(self, tmp_path):
        """When a selections file exists, it's read and applied during execution."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(
                        id="img1",
                        source=ImageSource(
                            prompt="a hero shot",
                            candidates=[{"prompt": "alt hero"}],
                            select=1,
                        ),
                    ),
                ]),
            ],
        )

        # First run: generates candidates, pauses
        result1 = execute_timeline(tl, tmp_path, stage="images", mock=True)
        assert result1.pending_exploration == "images"

        # Simulate user creating selections file — pick candidate 1
        selections = {"img1": [1]}
        sel_path = tmp_path / "selections_images.json"
        sel_path.write_text(json.dumps(selections))

        # Second run (resume): should apply selections and continue
        result2 = execute_timeline(tl, tmp_path, stage="images", mock=True, resume=True)

        assert result2.pending_exploration is None
        assert result2.success is True
        assert "img1" in result2.results
        # The result should point to the candidate_1 path
        img1_path = result2.results["img1"].path
        assert "candidate_1" in str(img1_path)


# ---------------------------------------------------------------------------
# Test: ExplorationState pause/resume flow
# ---------------------------------------------------------------------------

class TestExplorationStatePauseResume:
    def test_exploration_state_pause_called(self, tmp_path):
        """When ExplorationState is provided, pause() is called with the phase."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(
                        id="img1",
                        source=ImageSource(
                            prompt="test",
                            candidates=[{"prompt": "alt"}],
                            select=1,
                        ),
                    ),
                ]),
            ],
        )

        exploration_state = ExplorationState()

        # Pre-write a selections file so wait_for_selection can proceed
        # (the ExplorationState.resume will be called from another thread)
        import threading

        def resume_after_pause():
            """Wait for pause, write selections, then resume."""
            # Wait until paused
            for _ in range(100):
                if exploration_state.is_paused:
                    break
                import time
                time.sleep(0.01)

            # Write selections file
            selections = {"img1": [0]}
            sel_path = tmp_path / "selections_images.json"
            sel_path.write_text(json.dumps(selections))

            exploration_state.resume()

        t = threading.Thread(target=resume_after_pause, daemon=True)
        t.start()

        result = execute_timeline(
            tl, tmp_path, stage="images", mock=True,
            exploration_state=exploration_state,
        )

        t.join(timeout=5)

        # Should have completed without pending_exploration
        assert result.pending_exploration is None
        assert result.success is True
        assert "img1" in result.results


# ---------------------------------------------------------------------------
# Test: validate_selections error paths
# ---------------------------------------------------------------------------

class TestValidateSelectionsErrors:
    """Test error detection in validate_selections()."""

    def _make_manifest(self, pending=None):
        """Build a SelectionManifest with default pending selections."""
        from timeline.explorer import SelectionManifest, PendingSelection, CandidateInfo
        if pending is None:
            pending = [
                PendingSelection(
                    id="img1",
                    type="clip",
                    media_type="image",
                    select=1,
                    candidates=[
                        CandidateInfo(index=0, path=Path("images/img1.png"), prompt="default"),
                        CandidateInfo(index=1, path=Path("images/img1_candidate_1.png"), prompt="alt 1"),
                        CandidateInfo(index=2, path=Path("images/img1_candidate_2.png"), prompt="alt 2"),
                    ],
                ),
            ]
        return SelectionManifest(phase="images", pending_selections=pending)

    def test_missing_required_selection_id(self):
        """Missing selection for a required ID produces an error."""
        from timeline.explorer import validate_selections
        manifest = self._make_manifest()
        errors = validate_selections(manifest, {})  # no selections at all
        assert any("Missing selection for 'img1'" in e for e in errors)

    def test_unknown_selection_id(self):
        """Selection for an ID not in the manifest produces an error."""
        from timeline.explorer import validate_selections
        manifest = self._make_manifest()
        errors = validate_selections(manifest, {"img1": [0], "bogus": [0]})
        assert any("Unknown selection ID 'bogus'" in e for e in errors)

    def test_wrong_count_too_many(self):
        """Too many indices for a selection produces an error."""
        from timeline.explorer import validate_selections
        manifest = self._make_manifest()  # select=1
        errors = validate_selections(manifest, {"img1": [0, 1]})
        assert any("requires 1 choice(s), got 2" in e for e in errors)

    def test_wrong_count_too_few(self):
        """Too few indices for a selection produces an error."""
        from timeline.explorer import validate_selections, PendingSelection, CandidateInfo
        manifest = self._make_manifest(pending=[
            PendingSelection(
                id="img1", type="clip", media_type="image", select=2,
                candidates=[
                    CandidateInfo(index=0, path=Path("a.png"), prompt="a"),
                    CandidateInfo(index=1, path=Path("b.png"), prompt="b"),
                    CandidateInfo(index=2, path=Path("c.png"), prompt="c"),
                ],
            ),
        ])
        errors = validate_selections(manifest, {"img1": [0]})
        assert any("requires 2 choice(s), got 1" in e for e in errors)

    def test_out_of_range_index(self):
        """Index beyond candidate count produces an error."""
        from timeline.explorer import validate_selections
        manifest = self._make_manifest()  # 3 candidates (0-2)
        errors = validate_selections(manifest, {"img1": [5]})
        assert any("Index 5 out of bounds" in e for e in errors)

    def test_negative_index(self):
        """Negative index produces an error."""
        from timeline.explorer import validate_selections
        manifest = self._make_manifest()
        errors = validate_selections(manifest, {"img1": [-1]})
        assert any("Index -1 out of bounds" in e for e in errors)

    def test_duplicate_indices(self):
        """Duplicate indices produce an error."""
        from timeline.explorer import validate_selections, PendingSelection, CandidateInfo
        manifest = self._make_manifest(pending=[
            PendingSelection(
                id="img1", type="clip", media_type="image", select=2,
                candidates=[
                    CandidateInfo(index=0, path=Path("a.png"), prompt="a"),
                    CandidateInfo(index=1, path=Path("b.png"), prompt="b"),
                    CandidateInfo(index=2, path=Path("c.png"), prompt="c"),
                ],
            ),
        ])
        errors = validate_selections(manifest, {"img1": [1, 1]})
        assert any("Duplicate indices" in e for e in errors)

    def test_valid_selection_no_errors(self):
        """Valid selections produce no errors (sanity check)."""
        from timeline.explorer import validate_selections
        manifest = self._make_manifest()
        errors = validate_selections(manifest, {"img1": [1]})
        assert errors == []


# ---------------------------------------------------------------------------
# Test: write_selections double-write protection
# ---------------------------------------------------------------------------

class TestWriteSelectionsDoubleWrite:
    def test_double_write_raises_value_error(self, tmp_path):
        """Calling write_selections when file already exists raises ValueError."""
        write_selections({"img1": [0]}, "images", tmp_path)
        with pytest.raises(ValueError, match="Selections already exist"):
            write_selections({"img1": [1]}, "images", tmp_path)

    def test_different_phases_allowed(self, tmp_path):
        """Writing selections for different phases is allowed."""
        write_selections({"img1": [0]}, "images", tmp_path)
        # Should not raise for a different phase
        write_selections({"vid1": [0]}, "videos", tmp_path)


# ---------------------------------------------------------------------------
# Test: ExplorationState completed flag
# ---------------------------------------------------------------------------

_has_completed = hasattr(ExplorationState, "mark_completed")


@pytest.mark.skipif(not _has_completed, reason="ExplorationState.mark_completed not yet implemented")
class TestExplorationStateCompleted:
    def test_initial_not_completed(self):
        """A new ExplorationState is not completed."""
        state = ExplorationState()
        assert not state.completed

    def test_mark_completed_sets_flag(self):
        """After mark_completed(), completed returns True."""
        state = ExplorationState()
        state.pause("images")
        state.mark_completed()
        assert state.completed

    def test_mark_completed_unblocks_pause(self):
        """After mark_completed(), is_paused returns False."""
        state = ExplorationState()
        state.pause("images")
        assert state.is_paused
        state.mark_completed()
        assert not state.is_paused

    def test_mark_completed_wait_returns_immediately(self):
        """After mark_completed(), wait_for_selection returns immediately."""
        import time
        state = ExplorationState()
        state.pause("images")
        state.mark_completed()
        start = time.monotonic()
        result = state.wait_for_selection(timeout=5.0)
        elapsed = time.monotonic() - start
        assert result is True
        assert elapsed < 1.0  # Should be nearly instant


# ---------------------------------------------------------------------------
# Test: candidate override allowlist filtering
# ---------------------------------------------------------------------------

class TestCandidateOverrideAllowlist:
    """Test that disallowed override keys are filtered out before replace()."""

    def test_disallowed_keys_filtered_image(self, tmp_path):
        """ImageSource candidates with disallowed keys (model, reference_images)
        still generate successfully — disallowed keys are silently dropped."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(
                        id="img1",
                        source=ImageSource(
                            prompt="a hero shot",
                            candidates=[
                                {
                                    "prompt": "alt hero",
                                    "model": "evil-model",           # disallowed
                                    "reference_images": ["/etc/passwd"],  # disallowed
                                },
                            ],
                            select=1,
                        ),
                    ),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="images", mock=True)

        # Generation should succeed (disallowed keys filtered, not passed to replace)
        assert result.success is True
        assert "img1" in result.results
        assert "img1_candidate_1" in result.results

    def test_disallowed_keys_filtered_video(self, tmp_path):
        """VideoSource candidates with disallowed keys are filtered."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(
                        id="vid1",
                        source=VideoSource(
                            prompt="a scene",
                            candidates=[
                                {
                                    "prompt": "alt scene",
                                    "model": "evil-model",           # disallowed
                                    "first_frame": "/etc/passwd",    # disallowed
                                },
                            ],
                            select=1,
                        ),
                    ),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="videos", mock=True)

        assert result.success is True
        assert "vid1" in result.results
        assert "vid1_candidate_1" in result.results

    def test_disallowed_keys_filtered_tts(self, tmp_path):
        """TTSSource candidates with disallowed keys are filtered."""
        tl = _make_timeline(
            tracks=[
                Track(id="narration", type="narration", clips=[
                    Clip(
                        id="tts1",
                        source=TTSSource(
                            text="Hello world",
                            candidates=[
                                {
                                    "text": "Goodbye world",
                                    "model": "evil-model",  # disallowed
                                },
                            ],
                            select=1,
                        ),
                    ),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="images", mock=True)

        assert result.success is True
        assert "tts1" in result.results
        assert "tts1_candidate_1" in result.results

    def test_typo_field_filtered(self, tmp_path):
        """A candidate with a typo field name (e.g. 'promot') is filtered
        out by the allowlist, so the candidate generates with original defaults."""
        tl = _make_timeline(
            tracks=[
                Track(id="video", type="video", clips=[
                    Clip(
                        id="img1",
                        source=ImageSource(
                            prompt="a hero shot",
                            candidates=[
                                {"promot": "typo field"},  # not in allowlist → filtered
                            ],
                            select=1,
                        ),
                    ),
                ]),
            ],
        )

        result = execute_timeline(tl, tmp_path, stage="images", mock=True)

        # Should still succeed — typo key is filtered, candidate uses defaults
        assert result.success is True
        assert "img1" in result.results
        assert "img1_candidate_1" in result.results
