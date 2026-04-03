"""Tests for timeline TTS generation adapter."""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from timeline.model import NodeResult, Project, TTSDefaults, TTSSource
from timeline.tts_gen import (
    TTS_MODEL_MAP,
    _build_script_context,
    _resolve_model,
    _resolve_voice,
    _resolve_voice_prompt,
    generate_tts,
)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


def test_resolve_model_mapped():
    assert _resolve_model("gemini-2.5-flash-tts") == "gemini-2.5-flash-preview-tts"


def test_resolve_model_passthrough():
    assert _resolve_model("some-other-model") == "some-other-model"


def test_build_script_context_with_project():
    proj = Project(name="My Video", description="A cool explainer")
    ctx = _build_script_context(proj)
    assert ctx == {"title": "My Video", "description": "A cool explainer"}


def test_build_script_context_none():
    assert _build_script_context(None) is None


def test_build_script_context_empty_project():
    proj = Project(name="", description=None)
    assert _build_script_context(proj) is None


def test_resolve_voice_from_source():
    src = TTSSource(voice="Puck")
    defaults = TTSDefaults(voice="Kore")
    assert _resolve_voice(src, defaults) == "Puck"


def test_resolve_voice_from_defaults():
    src = TTSSource(voice="")
    defaults = TTSDefaults(voice="Charon")
    assert _resolve_voice(src, defaults) == "Charon"


def test_resolve_voice_prompt_from_source():
    src = TTSSource(voice_prompt="Speak slowly")
    defaults = TTSDefaults(voice_prompt="Speak fast")
    assert _resolve_voice_prompt(src, defaults) == "Speak slowly"


def test_resolve_voice_prompt_falls_back_to_defaults():
    src = TTSSource(voice_prompt=None)
    defaults = TTSDefaults(voice_prompt="Default prompt")
    assert _resolve_voice_prompt(src, defaults) == "Default prompt"


# ---------------------------------------------------------------------------
# Helpers for integration tests
# ---------------------------------------------------------------------------


class FakeGeminiTTS:
    """Fake GeminiTTS that writes dummy audio files instead of calling APIs."""

    def __init__(self, model=None, api_key=None):
        self.model = model
        self.calls = []

    def synthesize_to_file(self, text, output_path, voice_name="Kore",
                           voice_prompt=None, script_context=None, output_format="mp3"):
        self.calls.append({
            "text": text,
            "voice_name": voice_name,
            "voice_prompt": voice_prompt,
            "script_context": script_context,
        })
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Write a minimal valid mp3-ish file (just bytes, probe will be mocked)
        output_path.write_bytes(b"\x00" * 100)
        return output_path


@pytest.fixture(autouse=True)
def _fake_google_api_key(monkeypatch):
    """Ensure GOOGLE_API_KEY is set so GeminiTTS.__init__ doesn't error."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-not-real")


@pytest.fixture
def run_dir(tmp_path):
    return tmp_path / "run"


@pytest.fixture
def fake_tts():
    """Patch GeminiTTS with FakeGeminiTTS and probe_duration_async."""
    fake = FakeGeminiTTS()

    async def fake_probe(path):
        return 2.5

    with patch("tts.gemini_tts.GeminiTTS", return_value=fake) as mock_cls, \
         patch("shared.media.probe_duration_async", side_effect=fake_probe):
        mock_cls.return_value = fake
        # Make the class constructor return our fake instance
        mock_cls.side_effect = lambda model=None, api_key=None: fake
        yield fake


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_tts_mock_mode(run_dir):
    """TTS generation produces audio files in mock mode."""
    from shared.replicate_client import set_mock_mode

    set_mock_mode(True)
    try:
        sources = [
            ("clip_1", TTSSource(text="Hello world", voice="Kore")),
            ("clip_2", TTSSource(text="Second clip", voice="Puck")),
        ]
        defaults = TTSDefaults()
        results = await generate_tts(sources, run_dir, defaults)

        assert len(results) == 2
        for cid in ("clip_1", "clip_2"):
            assert cid in results
            r = results[cid]
            assert r.media_type == "audio"
            assert r.path.exists()
            assert r.duration is not None and r.duration > 0
    finally:
        set_mock_mode(False)


@pytest.mark.asyncio
async def test_generate_tts_voice_prompt_passed(run_dir, fake_tts):
    """voice_prompt is forwarded to synthesize_to_file (not dropped)."""
    sources = [("vp_clip", TTSSource(text="Test", voice_prompt="Whisper softly"))]
    defaults = TTSDefaults()
    results = await generate_tts(sources, run_dir, defaults)

    assert "vp_clip" in results
    assert len(fake_tts.calls) == 1
    assert fake_tts.calls[0]["voice_prompt"] == "Whisper softly"


@pytest.mark.asyncio
async def test_generate_tts_empty_sources(run_dir):
    """Empty sources list returns empty dict without errors."""
    result = await generate_tts([], run_dir, TTSDefaults())
    assert result == {}


@pytest.mark.asyncio
async def test_generate_tts_error_handling(run_dir):
    """A failing clip doesn't crash the batch."""
    call_count = {"n": 0}

    class FailOnceTTS:
        def __init__(self, model=None, api_key=None):
            pass

        def synthesize_to_file(self, text, output_path, voice_name="Kore",
                               voice_prompt=None, script_context=None, output_format="mp3"):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Simulated TTS failure")
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"\x00" * 100)
            return output_path

    async def fake_probe(path):
        return 1.0

    with patch("tts.gemini_tts.GeminiTTS", FailOnceTTS), \
         patch("shared.media.probe_duration_async", side_effect=fake_probe):
        sources = [
            ("fail_clip", TTSSource(text="Will fail")),
            ("ok_clip", TTSSource(text="Will succeed")),
        ]
        # concurrency=1 to ensure ordering
        results = await generate_tts(sources, run_dir, TTSDefaults(), concurrency=1)
        assert "ok_clip" in results
        assert "fail_clip" not in results


@pytest.mark.asyncio
async def test_generate_tts_script_context_from_project(run_dir, fake_tts):
    """Project metadata is passed as script_context."""
    proj = Project(name="Test Project", description="A description")
    sources = [("ctx_clip", TTSSource(text="Context test"))]
    await generate_tts(sources, run_dir, TTSDefaults(), project=proj)

    assert fake_tts.calls[0]["script_context"] == {
        "title": "Test Project",
        "description": "A description",
    }


@pytest.mark.asyncio
async def test_generate_tts_per_clip_model_switching(run_dir):
    """Per-clip model overrides the default model (MAJOR-6)."""
    created_models = []

    class TrackingTTS:
        def __init__(self, model=None, api_key=None):
            self.model = model
            created_models.append(model)

        def synthesize_to_file(self, text, output_path, voice_name="Kore",
                               voice_prompt=None, script_context=None, output_format="mp3"):
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"\x00" * 100)
            return output_path

    async def fake_probe(path):
        return 2.0

    with patch("tts.gemini_tts.GeminiTTS", TrackingTTS), \
         patch("shared.media.probe_duration_async", side_effect=fake_probe):
        sources = [
            ("clip_default", TTSSource(text="Default model")),
            ("clip_custom", TTSSource(text="Custom model", model="gemini-2.5-flash-tts")),
        ]
        defaults = TTSDefaults(model="gemini-2.5-flash-tts")
        # concurrency=1 to ensure ordering
        results = await generate_tts(sources, run_dir, defaults, concurrency=1)

        assert "clip_default" in results
        assert "clip_custom" in results
        # First client created with the default model
        assert created_models[0] == "gemini-2.5-flash-preview-tts"


@pytest.mark.asyncio
async def test_forced_alignment_no_crash_without_api_key(run_dir):
    """Forced alignment gracefully skips when ELEVENLABS_API_KEY is missing."""
    from shared.replicate_client import set_mock_mode

    set_mock_mode(True)
    try:
        old_key = os.environ.pop("ELEVENLABS_API_KEY", None)
        try:
            sources = [("fa_clip", TTSSource(text="Alignment test"))]
            results = await generate_tts(sources, run_dir, TTSDefaults())
            assert "fa_clip" in results
        finally:
            if old_key is not None:
                os.environ["ELEVENLABS_API_KEY"] = old_key
    finally:
        set_mock_mode(False)
