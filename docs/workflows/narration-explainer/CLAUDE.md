# narration-explainer — agent notes

Read this when the user wants a narrated explainer video — a TTS voiceover
explaining something, with a generated visual per beat. For the full
strategy, see `README.md`.

## How to drive this workflow

```bash
# Validate, then run via the project-aware wrapper
python scripts/timeline_validate.py <timeline.json>
python scripts/run.py <timeline.json> --stage final

# Iterate on stills only (cheap)
python scripts/run.py <timeline.json> --stage images --force-clip <vid-id>

# Iterate on motion (videos use existing stills)
python scripts/run.py <timeline.json> --stage videos
```

**Use `scripts/run.py`, not `pipeline.py` directly** — keeps everything
in `runs/<slug>/`.

## Defaults — pick these

- Video: `seedance-2.0-fast` at 480p, 16:9, **`generate_audio: false`**
  (narration IS the audio)
- Image: `nano-banana-pro` (or `gpt-image-2` if any text in the image)
- TTS: `Kore` (Gemini TTS, see `docs/reference/tts-voices.md` for alternatives)

## The shape

Two tracks — `narration` (TTS clips) and `video` (visuals). Each video
clip has `fit_to: "<narr-id>"` so the pipeline sizes the video to match
the narration's actual duration.

```json
{
  "tracks": [
    {"id": "narration", "type": "narration", "clips": [
      {"id": "narr-1", "source": {"type": "tts", "text": "..."}}
    ]},
    {"id": "visuals", "type": "video", "clips": [
      {"id": "vid-1", "fit_to": "narr-1", "source": {
        "type": "video",
        "prompt": "Animated motion description ...",
        "first_frame": {"generate": {"type": "image", "prompt": "Still description ..."}}
      }}
    ]}
  ]
}
```

## Critical rules

- **`fit_to` and `duration` don't mix.** If a video clip has `fit_to`, do
  NOT set `duration` — the pipeline computes it from the TTS length.
- **`generate_audio: false`** on `defaults.video` always. Otherwise
  Seedance writes audio that conflicts with narration.
- **WPS 2.5 budgeting**: keep narration clips ≤ ~30 words (≤ 12s).
  Seedance maxes at 15s per clip; longer narration must be split.
- **`first_frame.generate` and `reference_images` are mutually
  exclusive.** This workflow uses `first_frame.generate` exclusively —
  don't add character refs.

## Stage iteration — the workflow's killer feature

| User request | Run |
|---|---|
| "Try a different visual style for clip 3" | `--stage images --force-clip vid-3` |
| "I like the stills, retry the motion" | `--stage videos` |
| "Reorder / trim / final assembly" | `--stage final` |
| "Different TTS voice" | Edit `defaults.tts.voice`, then `--stage images --force` (TTS regens at images stage) |

The pipeline tracks per-stage completion in the run dir, so each `--stage`
invocation only does the work that stage represents.

## Single-subject discipline

This workflow's clips are short and visually focused — one subject per
clip, motion described concretely. **Don't stage multi-character scenes
in narration-explainer**. If the user wants a recurring cast, they want
`docs/workflows/news-video/` instead.

## Examples

- `tests/e2e_scripts/06_long_narration_timing.json` — long+short
  narration pair, exercises `fit_to`
- `tests/e2e_scripts/01_text_heavy_infographic.json` — text-on-screen
  visuals (uses `gpt-image-2`)
- `tests/e2e_scripts/04_multi_clip_scene.json` — multi-beat narrative
