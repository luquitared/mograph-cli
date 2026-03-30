# tts/

Text-to-speech synthesis, transcription, and audio timestamp processing. Primary TTS engine is Gemini 2.5 Flash; ElevenLabs provides forced alignment for precise word timestamps; Deepgram handles voice-mode transcription.

## Files

- `gemini_tts.py` — Primary TTS via Google Gemini 2.5 Flash. Handles batch synthesis with voice selection by Gemini voice name
- `eleven.py` — ElevenLabs TTS with `convert_with_timestamps` for character-level timing, and `forced_alignment_sync()` for word-level timestamps on pre-existing audio
- `transcribe.py` — Deepgram transcription for voice mode. Extracts word-level timestamps and formats for LLM consumption
- `tts_transcript.py` — Converts ElevenLabs/forced-alignment timestamps into `TTSTranscript` objects with word-level timing for TTS-first pipeline mode

## Key Interfaces

**gemini_tts.py:**
- `GeminiTTS` — Single-utterance TTS client (`synthesize_to_file()`)
- `BatchGeminiTTS` — Concurrent batch synthesis (`synthesize_batch()`)
- `synthesize_narration(script_data, output_dir, voice=...)` — High-level: synthesize all scenes from a script, voice selected by Gemini voice name (e.g., Kore, Puck, Charon)

**eleven.py:**
- `BatchTTS` — ElevenLabs batch TTS with timestamps (`synth_one()`)
- `forced_alignment_sync(audio_path, transcript)` — Get word-level timestamps for existing audio (used by pipeline.py for precise timing)
- `get_word_timestamps(alignment_result)` — Extract word timing from alignment

**transcribe.py:**
- `transcribe_audio(audio_path)` → `TranscriptionResult` with word timestamps
- `TranscriptionResult.to_llm_context()` — Format transcript for LLM scene generation

**tts_transcript.py:**
- `create_tts_transcript(text, timestamps_data)` → `TTSTranscript`
- `TTSTranscript.to_llm_context()` — Format for LLM consumption

## Dependencies

- **Imports from**: `shared.replicate_client` (is_mock_mode, is_tts_test_mode), `google.genai`, `elevenlabs`, `deepgram`
- **Imported by**: `pipeline.py` (lazy imports throughout)
