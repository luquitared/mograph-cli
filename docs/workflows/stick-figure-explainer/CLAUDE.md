# Stick-figure explainer — agent guide

**Read [`docs/workflows/narration-explainer/CLAUDE.md`](../narration-explainer/CLAUDE.md) first.** Its hard rules apply here verbatim: `fit_to: "narr-N"` on every video clip, no `duration` when `fit_to` is set, `generate_audio: false`, inline `first_frame.generate` (no separate `img-` clips, no `reference_images`), WPS 2.5 / ≤30 words per narration clip, run via `scripts/run.py`. This file only covers what's *different* about this recipe.

## What's different: the style

Use exactly this `defaults` block. The two `prompt_prefix` strings are non-negotiable — they bind the look across every clip.

```json
"defaults": {
  "image": {
    "model": "nano-banana-pro",
    "aspect_ratio": "16:9",
    "resolution": "2K",
    "output_format": "png",
    "prompt_prefix": "Simple hand-drawn minimal cartoon style on grey textured background, black outlines, stick figures."
  },
  "video": {
    "model": "seedance-2.0-fast",
    "aspect_ratio": "16:9",
    "resolution": "480p",
    "generate_audio": false,
    "prompt_prefix": "Simple hand-drawn minimal cartoon style on grey textured background, black outlines, stick figures."
  },
  "tts": {
    "voice": "Kore",
    "voice_prompt": "Casual, friendly, conversational tone. Like explaining to a friend."
  }
}
```

## Style-specific prompt patterns

- **"One X" framing on every concrete subject** — both in `first_frame.generate.prompt` and the video `prompt`. `One stick figure sits at one desk and panics at one laptop showing one red zig-zag price line.` Seedance composes cleaner this way.
- **Recognizable labeled props** — Bitcoin icon, golden token, wooden bridge, bank vault, magnifying glass, fenced zone. Put names on signs/screens: `Text reads 1 coin = 1 dollar.`
- **Tiny motion verbs only** — `wobbles`, `pulses softly`, `tips and spills`, `rotates slowly`, `drifts upward`. No camera moves.
- **Two-panel splits** — `Two-panel cartoon. Left panel: ... . Right panel: ...` for before/after.
- **The video prompt continues the still** — same scene as `first_frame.generate`, plus one or two motion verbs. Don't introduce new objects in the video that aren't in the still.

## Style-specific don'ts

- **Recurring named characters** — this recipe uses everyperson stick figures. Recurring cast → switch to `docs/workflows/character-asset/` for the sheet.
- **Photoreal celebrity/politician likenesses** — Seedance moderation rejects (E005). Stick figures sidestep this; don't break the abstraction.
- **Realistic shading or full color** — keep accents to one or two per beat (red, green, gold, blue).
- **Camera moves** — pans, dollies, zooms break the held-frame whiteboard aesthetic.

## Example

`examples/how-a-thermos-works.json` is the canonical worked example. Read it before authoring a new one.
