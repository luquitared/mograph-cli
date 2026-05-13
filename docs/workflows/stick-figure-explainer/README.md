# Stick-figure explainer

A style specialization of [`narration-explainer`](../narration-explainer/README.md). Read that first — it covers the two-track shape, `fit_to`, `first_frame.generate`, `generate_audio: false`, stage iteration, the WPS 2.5 budget, run commands, and pitfalls. **Everything here is just the look.**

## The look

Black-outline stick figures on grey textured paper. One or two accent colors per beat (red for danger, green for stability, gold for value, blue for cool). Lots of negative space. Held-frame whiteboard sketches with small deliberate motion — wobbles, rotations, things sliding into frame. No camera moves. Optional two-panel splits for before/after.

## Style spec — drop into `defaults`

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

The two `prompt_prefix` strings are what bind the look across every clip — don't remove them.

## Prompt patterns

After the prefix auto-prepends, write your scene prompt with these:

- **Lead every subject with "One"** — `One stick figure sits at one desk and panics at one laptop showing one red zig-zag price line.` Seedance honors single-subject framing when "one" is explicit, which keeps composition uncluttered.
- **Concrete labeled props** — `Bitcoin icon`, `golden token`, `wooden bridge`, `bank vault`. Stick figures need recognizable objects to carry meaning. When a name matters, put it on a sign: `counter labeled Stablecoin Exchange`, `Text reads 1 coin = 1 dollar.`
- **Tiny motion verbs only** — `wobbles`, `pulses softly`, `tips and spills`, `rotates slowly`, `drifts upward`, `nods`. No `pan`, `dolly`, `zoom`, `track` — the look is a sequence of held sketches, not cinematic shots.
- **Two-panel splits** — `Two-panel cartoon. Left panel: ... . Right panel: ...` for before/after, problem/solution, two characters.
- **Continue the still in the video** — the video prompt should describe the same scene as `first_frame.generate` + one or two motion verbs. Don't introduce new objects in the video that aren't in the still.

## Don't

- **Recurring named characters** — these are abstract everyperson stick figures. If a recurring cast matters, switch to [`character-asset`](../character-asset/README.md).
- **Photoreal celebrity/politician likenesses** — Seedance moderation rejects them (E005). Stick figures sidestep this; don't break the abstraction.
- **Realistic shading or full-color palettes** — keep accents to one or two per beat.

## Example

`examples/how-a-thermos-works.json` — 8 beats, ~53s, using the canonical `fit_to` + `first_frame.generate` pattern.
