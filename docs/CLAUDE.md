# docs/

Detailed reference documentation for the pipeline. The root `CLAUDE.md` has quick-start orientation; these files go deeper.

## Files

- `pipeline-modes.md` — Pipeline modes: timeline format, staged execution, exploration
- `cli-reference.md` — Full CLI argument reference for `pipeline.py`
- `tts-voices.md` — Gemini TTS configuration: voices and voice selection
- `deployment.md` — Cloud Run deployment architecture and setup
- `inspecting-runs.md` — How to find and inspect previous pipeline runs in GCS
- `e2e-testing.md` — End-to-end testing strategy and generation tracking
- `music-video-workflow.md` — End-to-end recipe for generating a cartoon music video from an mp3 (Gemini 3.1 analysis → Seedance gen → ffmpeg assemble)
- `character-asset/` — Recipe for producing a transparent character video asset (chroma-green render → locked-camera idle → VP8-alpha webm); use `scripts/key_character.py` for keying
