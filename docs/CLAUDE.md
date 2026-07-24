# docs/

Documentation index. Root `CLAUDE.md` and `README.md` cover quick orientation; this tree goes deeper.

## `workflows/` — pick a recipe

Each folder is a self-contained recipe for a kind of video. Match the folder to what the user is asking for, then read its `README.md` (human-facing) or `CLAUDE.md` (agent-facing strategy).

- `narration-explainer/` — TTS or pre-recorded VO + per-beat visuals
- `news-video/` — recurring on-screen cast, anchor + co-host + b-roll cutaways
- `music-video/` — mp3 → Gemini analysis → Seedance cuts → ffmpeg assemble
- `format-rip/` — clone an existing video's pacing/structure into a reusable pack
- `style-rip/` — clone an existing video's visual style into a reusable pack
- `character-asset/` — produce a transparent (alpha) character video asset; uses `scripts/key_character.py` for keying
- `video-clone/` — recreate an existing video shot-by-shot
- `voice-via-audio-ref/` — fix emotionless Seedance dialogue by passing a clean reference WAV (e.g. from Gemini TTS) as `reference_audios` on a stylized character clip

## `reference/` — coding-side reference

- `known-issues.md` — **read before shipping a render.** Silent `fit_to`/audio-truncation bug on resume, Seedance filename collisions, real measured WPS, adversarial QC pass
- `cli-reference.md` — full CLI argument reference for `pipeline.py`
- `pipeline-modes.md` — staged execution, exploration, dry-run
- `inspecting-runs.md` — finding past runs in GCS
- `tts-voices.md` — Gemini TTS voice catalog and selection guide
- `script-writer.md` — rules for engaging dialogue: bracket `[cue]` syntax for Gemini TTS text + Seedance prompt, do/don't list, before/after example
- `e2e-testing.md` — end-to-end testing strategy and generation tracking
- `timeline/format-reference.md` — every timeline JSON field, type, default, constraint
- `timeline/models.md` — per-model parameters, constraints, costs

## Deployment

Lives at top-level [`deployment/`](../deployment/) — script and docs co-located.
