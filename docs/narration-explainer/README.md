# Narration-Explainer Workflow

A pre-narrated explainer video: a script (or prerecorded VO) drives the
clip durations, and each clip is a generated visual that fits the
narration over it. Different shape than news-video — single voice,
single visual subject per clip, no recurring cast.

## When to use this workflow

- A topic the user wants explained over voiceover (history, science,
  product, technical)
- Each beat in the narration deserves its own visual
- No need for character continuity across clips — each scene is
  self-contained
- The user has a script in mind, or wants TTS to read one

If the user wants a recurring on-screen cast or interleaved b-roll
cutaways, they want `docs/news-video/` instead.

## Inputs

- `.env` with `REPLICATE_API_TOKEN` (Seedance + image gen) and
  `GOOGLE_API_KEY` (Gemini TTS)
- A timeline file with **two tracks**: a `narration` track of TTS clips
  and a `video` track whose clips `fit_to:` the narration clips

## Outputs

- `runs/<project>/audio/narr-*.wav` — TTS narration per clip
- `runs/<project>/images/<clip-id>.png` — generated first frames
- `runs/<project>/videos/<clip-id>.mp4` — animated clips
- `runs/<project>/final/video_with_narration.mp4` — final assembled

## Quick start

```bash
# Build a timeline (see Section 2). Then:
python scripts/timeline_validate.py <timeline.json>
python scripts/run.py <timeline.json>
```

The `run.py` wrapper handles project-stable dirs and auto-resume.

---

## 1. The two-track shape

```json
{
  "version": 1,
  "project": {"name": "Apollo 11 Explainer"},
  "defaults": {
    "video": {"model": "seedance-2.0-fast", "duration": 6, "generate_audio": false},
    "image": {"model": "nano-banana-pro", "aspect_ratio": "16:9"},
    "tts":   {"voice": "Kore"}
  },
  "tracks": [
    {
      "id": "narration",
      "type": "narration",
      "clips": [
        {"id": "narr-1", "source": {"type": "tts", "text": "..."}},
        {"id": "narr-2", "source": {"type": "tts", "text": "..."}}
      ]
    },
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-1",
          "fit_to": "narr-1",
          "source": {
            "type": "video",
            "prompt": "Camera tracks upward as the rocket lifts off ...",
            "first_frame": {"generate": {"type": "image", "prompt": "Saturn V on launch pad ..."}}
          }
        }
      ]
    }
  ]
}
```

Key field: **`fit_to: "narr-X"`** on each video clip. The pipeline measures
the TTS clip's actual duration and sizes the video to match. **Critical**:
TTS is unpredictable in length — don't hardcode `duration` on video clips
that have `fit_to`.

`generate_audio: false` on the video defaults — the narration IS the
audio.

---

## 2. Stage-by-stage iteration (the win for this workflow)

`pipeline.py --stage <name>` lets you rerun individual stages. This is
the iteration shape this workflow was built for:

| Stage | What runs | When to rerun |
|---|---|---|
| `images` | TTS narration + first-frame images | Different narration voice; visual style swap on the still |
| `videos` | Animates each first-frame into an 8-second clip | Tweaking motion only — TTS and stills stay |
| `final` | Concats videos with narration audio overlay | Trimming, ordering, output format |

```bash
# First pass — generate everything
python scripts/run.py timeline.json --stage final

# Hate the visual style on one image — rerun images stage only
python scripts/run.py timeline.json --stage images --force-clip vid-3

# Like the stills, want to retry the motion — rerun videos stage
python scripts/run.py timeline.json --stage videos
```

`run.py` always passes `--resume-dir`, so rerunning a stage skips work
already done in earlier stages.

---

## 3. Script writing — WPS 2.5

Same rule as news-video: count words in your narration, divide by 2.5,
that's the playback duration. The pipeline computes the actual TTS
duration and sizes videos via `fit_to` — but if you write a 200-word
paragraph you'll get a 80-second clip, which will exhaust Seedance's
15-second per-clip cap. **Keep narration clips to ~30 words / 12 seconds
or less.** Break long thoughts across multiple narration clips.

---

## 4. Visual prompts — single-subject

Unlike news-video where each clip stages 3 characters at a desk,
explainer clips are usually single-subject scenes:

- A rocket lifting off (one subject, motion)
- A footprint on the moon (one subject, contemplative)
- A circuit diagram zooming in (one subject, animated)

Tighter scope helps Seedance animate well. **Avoid multi-subject scenes
in this workflow** — use cuts (separate clips) for transitions instead.

---

## 5. Image models — pick by the still you want

- **`nano-banana-pro`** — Gemini 3.1 Flash Image via Replicate. Solid
  default for photorealistic and illustrated stills. Has built-in
  quality verification.
- **`nano-banana-2`** — Same model, Gemini direct API, burst mode. Use
  when generating many stills in parallel and you don't need the
  Replicate-side verification.
- **`gpt-image-2`** — OpenAI via Replicate. Best when you need text
  rendered cleanly inside the image (signs, captions, UI).

Set the model on `defaults.image` in the timeline.

---

## 6. TTS voices

`defaults.tts.voice` selects a Gemini TTS voice. See
`docs/tts-voices.md` for the catalog. Defaults to `Kore` if unset.

To override per-clip: `narration` clip's `source.voice: "<name>"`.

---

## 7. Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Video duration doesn't match narration | Hardcoded `duration` on a video clip that has `fit_to` | Remove the `duration` — let `fit_to` size it |
| Seedance E006 — duration < 4 | Narration clip too short, `fit_to` wants <4s | Pad narration text or merge with the next clip |
| Narration runs past the video | Narration text too long for one clip | Split into multiple narration clips and matching video clips |
| Final video has no audio | `generate_audio: true` on video clips wrote audio that overrode narration | Set `generate_audio: false` on `defaults.video` |
| First-frame image doesn't match the video motion | Image and video prompts are independent — the model improvises | Make the video prompt explicitly continue from the still ("Camera holds on the [first frame description], then ...") |

---

## 8. Examples

`tests/e2e_scripts/06_long_narration_timing.json` exercises a long-then-
short narration pair — useful as a reference for `fit_to` semantics.

The other `tests/e2e_scripts/0X_*.json` files are e2e fixtures with the
two-track narration+visual shape.
