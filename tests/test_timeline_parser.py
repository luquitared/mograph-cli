"""Tests for timeline/parser.py — JSON parsing and normalization."""

import json
import tempfile
from pathlib import Path

import pytest

from timeline.model import (
    Clip,
    FileSource,
    Generate,
    ImageSource,
    Ref,
    SilenceSource,
    StillSource,
    TTSSource,
    VideoSource,
)
from timeline.parser import TimelineParseError, get_warnings, parse_timeline


# ---------------------------------------------------------------------------
# Minimal valid timeline dict
# ---------------------------------------------------------------------------

def _minimal_timeline(**overrides) -> dict:
    """Build a minimal valid timeline dict with optional overrides."""
    base = {
        "version": 1,
        "project": {"name": "Test Project"},
        "tracks": [
            {
                "id": "main",
                "type": "video",
                "clips": [
                    {
                        "id": "clip-1",
                        "source": {
                            "type": "video",
                            "prompt": "A test video",
                        },
                    }
                ],
            }
        ],
    }
    base.update(overrides)
    return base


def _full_timeline() -> dict:
    """Build a full-featured timeline with all source types."""
    return {
        "version": 1,
        "project": {
            "name": "Full Test",
            "description": "All source types",
            "aspect_ratio": "16:9",
            "resolution": "1080p",
        },
        "defaults": {
            "video": {"model": "veo-3.1-lite", "duration": 8},
            "image": {"model": "nano-banana-pro", "reference_images": ["default.png"]},
            "tts": {"voice": "Zephyr"},
        },
        "assets": {
            "img-1": {
                "type": "image",
                "prompt": "A green leaf",
            }
        },
        "tracks": [
            {
                "id": "narration",
                "type": "narration",
                "clips": [
                    {
                        "id": "narr-1",
                        "source": {"type": "tts", "text": "Hello world"},
                    },
                    {
                        "id": "silence-1",
                        "source": {"type": "silence", "duration": 1.5},
                    },
                ],
            },
            {
                "id": "video-track",
                "type": "video",
                "clips": [
                    {
                        "id": "vid-1",
                        "source": {
                            "type": "video",
                            "prompt": "Leaf swaying",
                            "first_frame": {"ref": "img-1"},
                            "duration": 6,
                        },
                    },
                    {
                        "id": "still-1",
                        "source": {
                            "type": "still",
                            "image": {"ref": "img-1"},
                            "duration": 3,
                        },
                    },
                ],
            },
            {
                "id": "audio-track",
                "type": "audio",
                "clips": [
                    {
                        "id": "music-1",
                        "source": {
                            "type": "file",
                            "path": "assets/music.mp3",
                            "start": 0.0,
                            "end": 30.0,
                        },
                    }
                ],
            },
        ],
        "output": {"format": "mp4"},
    }


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------

class TestBasicParsing:
    def test_parse_minimal_dict(self):
        tl = parse_timeline(_minimal_timeline())
        assert tl.version == 1
        assert tl.project.name == "Test Project"
        assert len(tl.tracks) == 1
        assert len(tl.tracks[0].clips) == 1

    def test_parse_full_dict(self):
        tl = parse_timeline(_full_timeline())
        assert tl.project.name == "Full Test"
        assert tl.project.resolution == "1080p"
        assert len(tl.tracks) == 3
        assert "img-1" in tl.assets

    def test_parse_from_file(self, tmp_path):
        f = tmp_path / "timeline.json"
        f.write_text(json.dumps(_minimal_timeline()))
        tl = parse_timeline(f)
        assert tl.project.name == "Test Project"

    def test_parse_from_string_path(self, tmp_path):
        f = tmp_path / "timeline.json"
        f.write_text(json.dumps(_minimal_timeline()))
        tl = parse_timeline(str(f))
        assert tl.project.name == "Test Project"


# ---------------------------------------------------------------------------
# Version gate (REQ-PARSE-003)
# ---------------------------------------------------------------------------

class TestVersionGate:
    def test_version_2_rejected(self):
        with pytest.raises(TimelineParseError, match="Unsupported timeline version"):
            parse_timeline(_minimal_timeline(version=2))

    def test_version_0_rejected(self):
        with pytest.raises(TimelineParseError, match="Unsupported timeline version"):
            parse_timeline(_minimal_timeline(version=0))

    def test_missing_version(self):
        d = _minimal_timeline()
        del d["version"]
        with pytest.raises(TimelineParseError, match="Missing required field.*version"):
            parse_timeline(d)


# ---------------------------------------------------------------------------
# Required fields (REQ-PARSE-004)
# ---------------------------------------------------------------------------

class TestRequiredFields:
    def test_missing_project(self):
        d = _minimal_timeline()
        del d["project"]
        with pytest.raises(TimelineParseError, match="Missing required field.*project"):
            parse_timeline(d)

    def test_missing_tracks(self):
        d = _minimal_timeline()
        del d["tracks"]
        with pytest.raises(TimelineParseError, match="Missing required field.*tracks"):
            parse_timeline(d)

    def test_missing_project_name(self):
        d = _minimal_timeline()
        d["project"] = {"description": "no name"}
        with pytest.raises(TimelineParseError, match="project.name.*required"):
            parse_timeline(d)


# ---------------------------------------------------------------------------
# Project defaults (REQ-PARSE-005)
# ---------------------------------------------------------------------------

class TestProjectDefaults:
    def test_default_aspect_ratio(self):
        tl = parse_timeline(_minimal_timeline())
        assert tl.project.aspect_ratio == "16:9"

    def test_default_resolution(self):
        tl = parse_timeline(_minimal_timeline())
        assert tl.project.resolution == "720p"

    def test_custom_values(self):
        d = _minimal_timeline()
        d["project"]["aspect_ratio"] = "9:16"
        d["project"]["resolution"] = "1080p"
        tl = parse_timeline(d)
        assert tl.project.aspect_ratio == "9:16"
        assert tl.project.resolution == "1080p"


# ---------------------------------------------------------------------------
# Defaults normalization (REQ-PARSE-006, REQ-PARSE-007)
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_defaults_applied_to_video_source(self):
        d = _minimal_timeline()
        d["defaults"] = {"video": {"model": "veo-3.1-lite", "duration": 8}}
        tl = parse_timeline(d)
        vid = tl.tracks[0].clips[0].source
        assert isinstance(vid, VideoSource)
        assert vid.model == "veo-3.1-lite"
        assert vid.duration == 8

    def test_clip_overrides_defaults(self):
        """Clip-level values replace defaults (REQ-PARSE-007)."""
        d = _minimal_timeline()
        d["defaults"] = {"video": {"model": "veo-3.1-lite", "duration": 8}}
        d["tracks"][0]["clips"][0]["source"]["model"] = "seedance-2.0"
        d["tracks"][0]["clips"][0]["source"]["duration"] = 4
        tl = parse_timeline(d)
        vid = tl.tracks[0].clips[0].source
        assert isinstance(vid, VideoSource)
        assert vid.model == "seedance-2.0"
        assert vid.duration == 4

    def test_reference_images_replace_not_merge(self):
        """reference_images on a source fully replaces defaults (REQ-PARSE-007)."""
        d = {
            "version": 1,
            "project": {"name": "Test"},
            "defaults": {"image": {"reference_images": ["default.png"]}},
            "assets": {
                "img-1": {
                    "type": "image",
                    "prompt": "test",
                    "reference_images": ["custom.png"],
                }
            },
            "tracks": [
                {
                    "id": "v",
                    "type": "video",
                    "clips": [
                        {"id": "c1", "source": {"type": "video", "prompt": "x"}},
                    ],
                }
            ],
        }
        tl = parse_timeline(d)
        img = tl.assets["img-1"]
        assert isinstance(img, ImageSource)
        assert img.reference_images == ["custom.png"]

    def test_reference_images_inherits_default_when_absent(self):
        """When reference_images is not on the source, defaults apply."""
        d = {
            "version": 1,
            "project": {"name": "Test"},
            "defaults": {"image": {"reference_images": ["default.png"]}},
            "assets": {
                "img-1": {
                    "type": "image",
                    "prompt": "test",
                }
            },
            "tracks": [
                {
                    "id": "v",
                    "type": "video",
                    "clips": [
                        {"id": "c1", "source": {"type": "video", "prompt": "x"}},
                    ],
                }
            ],
        }
        tl = parse_timeline(d)
        img = tl.assets["img-1"]
        assert isinstance(img, ImageSource)
        assert img.reference_images == ["default.png"]

    def test_tts_defaults(self):
        d = {
            "version": 1,
            "project": {"name": "Test"},
            "defaults": {"tts": {"voice": "Zephyr", "voice_prompt": "Calm tone"}},
            "tracks": [
                {
                    "id": "narr",
                    "type": "narration",
                    "clips": [
                        {"id": "n1", "source": {"type": "tts", "text": "Hello"}},
                    ],
                }
            ],
        }
        tl = parse_timeline(d)
        tts = tl.tracks[0].clips[0].source
        assert isinstance(tts, TTSSource)
        assert tts.voice == "Zephyr"
        assert tts.voice_prompt == "Calm tone"


# ---------------------------------------------------------------------------
# Source type parsing
# ---------------------------------------------------------------------------

class TestSourceTypes:
    def test_image_source(self):
        d = {
            "version": 1,
            "project": {"name": "Test"},
            "assets": {"i1": {"type": "image", "prompt": "leaf"}},
            "tracks": [{"id": "v", "type": "video", "clips": [
                {"id": "c1", "source": {"type": "video", "prompt": "x"}}
            ]}],
        }
        tl = parse_timeline(d)
        assert isinstance(tl.assets["i1"], ImageSource)
        assert tl.assets["i1"].prompt == "leaf"

    def test_video_source(self):
        tl = parse_timeline(_minimal_timeline())
        vid = tl.tracks[0].clips[0].source
        assert isinstance(vid, VideoSource)

    def test_tts_source(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"] = {"type": "tts", "text": "Hello"}
        tl = parse_timeline(d)
        assert isinstance(tl.tracks[0].clips[0].source, TTSSource)

    def test_file_source(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"] = {"type": "file", "path": "music.mp3"}
        tl = parse_timeline(d)
        src = tl.tracks[0].clips[0].source
        assert isinstance(src, FileSource)
        assert src.path == "music.mp3"

    def test_silence_source(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"] = {"type": "silence", "duration": 2.0}
        tl = parse_timeline(d)
        src = tl.tracks[0].clips[0].source
        assert isinstance(src, SilenceSource)
        assert src.duration == 2.0

    def test_still_source(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"] = {
            "type": "still",
            "image": "photo.png",
            "duration": 3.0,
        }
        tl = parse_timeline(d)
        src = tl.tracks[0].clips[0].source
        assert isinstance(src, StillSource)
        assert src.image == "photo.png"
        assert src.duration == 3.0

    def test_unknown_source_type_rejected(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"] = {"type": "magic", "prompt": "x"}
        with pytest.raises(TimelineParseError, match="Unknown source type.*magic"):
            parse_timeline(d)


# ---------------------------------------------------------------------------
# Ref and Generate parsing
# ---------------------------------------------------------------------------

class TestRefGenerate:
    def test_ref_parsing(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"]["first_frame"] = {"ref": "img-1"}
        tl = parse_timeline(d)
        vid = tl.tracks[0].clips[0].source
        assert isinstance(vid.first_frame, Ref)
        assert vid.first_frame.ref == "img-1"
        assert vid.first_frame.extract is None

    def test_ref_with_extract(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"]["first_frame"] = {
            "ref": "vid-0",
            "extract": "last_frame",
        }
        tl = parse_timeline(d)
        vid = tl.tracks[0].clips[0].source
        assert isinstance(vid.first_frame, Ref)
        assert vid.first_frame.extract == "last_frame"

    def test_generate_parsing(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"]["first_frame"] = {
            "generate": {
                "type": "image",
                "prompt": "A leaf",
            }
        }
        tl = parse_timeline(d)
        vid = tl.tracks[0].clips[0].source
        assert isinstance(vid.first_frame, Generate)
        assert isinstance(vid.first_frame.generate, ImageSource)
        assert vid.first_frame.generate.prompt == "A leaf"

    def test_string_frame_input(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"]["first_frame"] = "path/to/image.png"
        tl = parse_timeline(d)
        vid = tl.tracks[0].clips[0].source
        assert vid.first_frame == "path/to/image.png"

    def test_null_frame_input(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"]["first_frame"] = None
        tl = parse_timeline(d)
        vid = tl.tracks[0].clips[0].source
        assert vid.first_frame is None

    def test_still_with_ref_image(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"] = {
            "type": "still",
            "image": {"ref": "asset-1"},
            "duration": 2.0,
        }
        tl = parse_timeline(d)
        src = tl.tracks[0].clips[0].source
        assert isinstance(src, StillSource)
        assert isinstance(src.image, Ref)
        assert src.image.ref == "asset-1"


# ---------------------------------------------------------------------------
# Canonical name enforcement (REQ-PARSE-009)
# ---------------------------------------------------------------------------

class TestCanonicalNames:
    @pytest.mark.parametrize("alias,hint", [
        ("first_frame_image", "first_frame"),
        ("last_frame_image", "last_frame"),
        ("image_paths", "reference_images"),
        ("start_image", "first_frame"),
        ("end_image", "last_frame"),
        ("image_input", "reference_images"),
    ])
    def test_alias_rejected_in_source(self, alias, hint):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"][alias] = "something"
        with pytest.raises(TimelineParseError, match=f"Non-canonical.*{alias}.*{hint}"):
            parse_timeline(d)

    def test_alias_rejected_at_clip_level(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["first_frame_image"] = "x"
        with pytest.raises(TimelineParseError, match="Non-canonical.*first_frame_image"):
            parse_timeline(d)


# ---------------------------------------------------------------------------
# Unknown field detection (REQ-PARSE-010)
# ---------------------------------------------------------------------------

class TestUnknownFields:
    def test_unknown_top_level_field_warns(self):
        d = _minimal_timeline()
        d["extra_field"] = "value"
        tl = parse_timeline(d)
        warnings = get_warnings(tl)
        assert any("extra_field" in w for w in warnings)

    def test_unknown_source_field_warns(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"]["unknown_param"] = True
        tl = parse_timeline(d)
        warnings = get_warnings(tl)
        assert any("unknown_param" in w for w in warnings)

    def test_underscore_prefixed_ignored(self):
        d = _minimal_timeline()
        d["_comment"] = "This is a comment"
        d["tracks"][0]["clips"][0]["source"]["_note"] = "internal"
        tl = parse_timeline(d)
        warnings = get_warnings(tl)
        assert not any("_comment" in w for w in warnings)
        assert not any("_note" in w for w in warnings)


# ---------------------------------------------------------------------------
# File size limit
# ---------------------------------------------------------------------------

class TestFileSize:
    def test_large_file_rejected(self, tmp_path):
        f = tmp_path / "huge.json"
        # Write > 1MB of JSON
        data = {"version": 1, "project": {"name": "x"}, "tracks": [], "pad": "x" * 1_100_000}
        f.write_text(json.dumps(data))
        with pytest.raises(TimelineParseError, match="exceeds maximum size"):
            parse_timeline(f)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

class TestErrorPaths:
    def test_invalid_json_file(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json {{{")
        with pytest.raises(TimelineParseError, match="Invalid JSON"):
            parse_timeline(f)

    def test_non_dict_top_level(self):
        with pytest.raises(TimelineParseError, match="must be a JSON object"):
            parse_timeline([1, 2, 3])  # type: ignore

    def test_source_missing_type(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"] = {"prompt": "no type"}
        with pytest.raises(TimelineParseError, match="missing required 'type'"):
            parse_timeline(d)

    def test_nonexistent_file(self):
        with pytest.raises(TimelineParseError, match="Cannot read"):
            parse_timeline("/nonexistent/path/timeline.json")

    def test_invalid_frame_input_dict(self):
        d = _minimal_timeline()
        d["tracks"][0]["clips"][0]["source"]["first_frame"] = {"bad_key": "val"}
        with pytest.raises(TimelineParseError, match="must have 'ref' or 'generate'"):
            parse_timeline(d)


# ---------------------------------------------------------------------------
# Narration sugar
# ---------------------------------------------------------------------------

class TestNarrationSugar:
    def _video_track_with_narration(self, narration, **clip_overrides):
        """Build a timeline with a single video clip that has narration sugar."""
        clip = {
            "id": "vid-1",
            "narration": narration,
            "source": {"type": "video", "prompt": "A test video"},
        }
        clip.update(clip_overrides)
        return {
            "version": 1,
            "project": {"name": "Test"},
            "tracks": [
                {"id": "visuals", "type": "video", "clips": [clip]},
            ],
        }

    def test_string_shorthand(self):
        tl = parse_timeline(self._video_track_with_narration("Hello world"))
        # Should create a narration track
        assert len(tl.tracks) == 2
        narr_track = [t for t in tl.tracks if t.type == "narration"][0]
        assert len(narr_track.clips) == 1
        assert narr_track.clips[0].id == "vid-1-narration"
        tts = narr_track.clips[0].source
        assert isinstance(tts, TTSSource)
        assert tts.text == "Hello world"
        # Video clip should have fit_to set
        vid_clip = [t for t in tl.tracks if t.type == "video"][0].clips[0]
        assert vid_clip.fit_to == "vid-1-narration"

    def test_object_form_with_text(self):
        tl = parse_timeline(self._video_track_with_narration({"text": "Hello world"}))
        narr_track = [t for t in tl.tracks if t.type == "narration"][0]
        tts = narr_track.clips[0].source
        assert isinstance(tts, TTSSource)
        assert tts.text == "Hello world"

    def test_voice_override(self):
        tl = parse_timeline(self._video_track_with_narration({
            "text": "Hello",
            "voice": "Aoede",
        }))
        narr_track = [t for t in tl.tracks if t.type == "narration"][0]
        tts = narr_track.clips[0].source
        assert tts.voice == "Aoede"

    def test_voice_prompt_override(self):
        tl = parse_timeline(self._video_track_with_narration({
            "text": "Hello",
            "voice_prompt": "Speak slowly and clearly",
        }))
        narr_track = [t for t in tl.tracks if t.type == "narration"][0]
        tts = narr_track.clips[0].source
        assert tts.voice_prompt == "Speak slowly and clearly"

    def test_fit_method_from_narration(self):
        tl = parse_timeline(self._video_track_with_narration({
            "text": "Hello",
            "fit_method": "speed",
        }))
        vid_clip = [t for t in tl.tracks if t.type == "video"][0].clips[0]
        assert vid_clip.fit_method == "speed"
        assert vid_clip.fit_to == "vid-1-narration"

    def test_tts_defaults_applied(self):
        d = self._video_track_with_narration({"text": "Hello"})
        d["defaults"] = {"tts": {"voice": "Zephyr", "voice_prompt": "Calm tone"}}
        tl = parse_timeline(d)
        narr_track = [t for t in tl.tracks if t.type == "narration"][0]
        tts = narr_track.clips[0].source
        assert tts.voice == "Zephyr"
        assert tts.voice_prompt == "Calm tone"

    def test_multiple_clips_with_narration(self):
        d = {
            "version": 1,
            "project": {"name": "Test"},
            "tracks": [
                {
                    "id": "visuals",
                    "type": "video",
                    "clips": [
                        {
                            "id": "vid-1",
                            "narration": {"text": "First part"},
                            "source": {"type": "video", "prompt": "Scene 1"},
                        },
                        {
                            "id": "vid-2",
                            "narration": {"text": "Second part"},
                            "source": {"type": "video", "prompt": "Scene 2"},
                        },
                    ],
                }
            ],
        }
        tl = parse_timeline(d)
        narr_track = [t for t in tl.tracks if t.type == "narration"][0]
        assert len(narr_track.clips) == 2
        assert narr_track.clips[0].id == "vid-1-narration"
        assert narr_track.clips[1].id == "vid-2-narration"
        # Both video clips should have fit_to
        vid_track = [t for t in tl.tracks if t.type == "video"][0]
        assert vid_track.clips[0].fit_to == "vid-1-narration"
        assert vid_track.clips[1].fit_to == "vid-2-narration"

    def test_appends_to_existing_narration_track(self):
        d = {
            "version": 1,
            "project": {"name": "Test"},
            "tracks": [
                {
                    "id": "narration",
                    "type": "narration",
                    "clips": [
                        {"id": "narr-intro", "source": {"type": "tts", "text": "Intro"}},
                    ],
                },
                {
                    "id": "visuals",
                    "type": "video",
                    "clips": [
                        {
                            "id": "vid-1",
                            "narration": {"text": "Main content"},
                            "source": {"type": "video", "prompt": "Scene 1"},
                        },
                    ],
                },
            ],
        }
        tl = parse_timeline(d)
        narr_tracks = [t for t in tl.tracks if t.type == "narration"]
        assert len(narr_tracks) == 1
        assert len(narr_tracks[0].clips) == 2
        assert narr_tracks[0].clips[0].id == "narr-intro"
        assert narr_tracks[0].clips[1].id == "vid-1-narration"

    def test_conflict_narration_and_fit_to(self):
        with pytest.raises(TimelineParseError, match="cannot have both 'narration' and 'fit_to'"):
            parse_timeline(self._video_track_with_narration(
                {"text": "Hello"},
                fit_to="some-clip",
            ))

    def test_narration_on_narration_track_rejected(self):
        d = {
            "version": 1,
            "project": {"name": "Test"},
            "tracks": [
                {
                    "id": "narr",
                    "type": "narration",
                    "clips": [
                        {
                            "id": "n1",
                            "narration": {"text": "Bad"},
                            "source": {"type": "tts", "text": "Hello"},
                        },
                    ],
                }
            ],
        }
        with pytest.raises(TimelineParseError, match="narration track cannot use 'narration' shorthand"):
            parse_timeline(d)

    def test_missing_text_rejected(self):
        with pytest.raises(TimelineParseError, match="narration.text.*required"):
            parse_timeline(self._video_track_with_narration({"voice": "Kore"}))

    def test_unknown_narration_field_rejected(self):
        with pytest.raises(TimelineParseError, match="Unknown narration field"):
            parse_timeline(self._video_track_with_narration({
                "text": "Hello",
                "bad_field": "value",
            }))

    def test_narration_underscore_fields_ignored(self):
        tl = parse_timeline(self._video_track_with_narration({
            "text": "Hello",
            "_comment": "this is fine",
        }))
        narr_track = [t for t in tl.tracks if t.type == "narration"][0]
        assert narr_track.clips[0].source.text == "Hello"
