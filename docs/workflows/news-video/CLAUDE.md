# news-video — agent notes

Read this when the user wants a news-segment-style video (anchor + co-host
+ fact source character at a desk, with topic intros and b-roll cutaways).
For the human-facing strategy, see `README.md`.

## How to drive this workflow

```bash
# 1. Pull example assets (one-time per machine)
python scripts/asset_pack_pull.py news-show-v1
# → runs/asset-packs/news-show-v1/{characters,voices,environments,composites}/

# 2. Validate before running (catches bad paths, moderation triggers, WPS overflows)
python scripts/timeline_validate.py <timeline.json>

# 3. Run via the project-aware wrapper (NOT pipeline.py directly)
python scripts/run.py <timeline.json>
# → runs/<slug>/  (stable dir, --resume by default, state.json written)

# 4. Inspect status
python scripts/runs_inspect.py <slug>

# 5. Re-render one clip (e.g. after a moderation hit or to tweak a joke)
python scripts/clip_replace.py <slug> <clip-id> [--prompt "new line"]

# 6. Audio polish (loudnorm + concat)
python scripts/polish_audio.py runs/<slug>
```

**Always use `scripts/run.py` and `scripts/clip_replace.py`** — they keep
all output in `runs/<slug>/`. Calling `pipeline.py` directly creates a new
timestamped dir per invocation and you'll end up merging clips by hand.

## Defaults — pick these unless the user says otherwise

- Video: **`seedance-2.0-fast`** at 480p, 16:9 (cheapest at $0.06/s).
- Image refs: **`gpt-image-2`** for composites with text on monitors
  (best text rendering); **`nano-banana-2`** for fast batches without text.
- Audio polish: **always** run after the pipeline finishes.

## Hard constraints (Seedance — these will fail your run)

- `duration` must be **integer 4–15** (or `-1` for auto). Lower bounds out
  with E006.
- `first_frame` and `reference_images` are **mutually exclusive**.
- `reference_audios` requires at least one `reference_images` or
  `reference_videos` entry — otherwise E006.
- WPS 2.5 — count words in your dialogue, divide by 2.5, that's your
  minimum duration. Add 1–2s buffer.

## Moderation pitfalls (will burn 3–5 min of retries before failing)

- **Photoreal-human reference images** (action figures, photo composites)
  trip E005. Stylized refs (anime, claymation, illustrated) pass.
- **Named studios in prompts** ("Studio Ghibli", "Robot Chicken", "Pixar")
  trigger a copyright block. Describe the aesthetic instead.
- **Recognizable political figures rendered as faces** in any reference
  image trigger a separate "may be related to copyright" block — distinct
  from E005. Use silhouette / symbolic imagery / caption-only on TV
  monitors. Spoken names in dialogue are fine; the visual is what trips.
- E003 capacity errors on `seedance-2.0-fast` — try again later, or
  switch to `seedance-2.0` (different pool, ~5x cost).

`scripts/timeline_validate.py` flags the first three as warnings before
you run.

## Patterns

- **Cast continuity:** pass each character's sheet as `reference_images`
  in every clip they appear in. For voice, extract a 5–10s WAV from the
  first generated clip and pass it in `reference_audios` thereafter.
- **Topic-introducing composite:** generate a single image with the cast
  at the desk + topic figure on the central TV monitor + bold caption.
  Pass it as `ref[0]` in every clip about that topic. Lets the dialogue
  use a clear noun-with-antecedent.
- **B-roll cutaways:** `"NO CHARACTERS visible on camera"` in the prompt,
  pass a scene ref + a voice ref. Lead with `"FULLY ANIMATED, CONTINUOUS
  MOTION THROUGHOUT"` or Seedance treats the ref as a locked still.
- **Topic-clip prompt skeleton:** `[0.0s-2.0s] HOLD on establishing shot
  — title card visible on TV. [2.0s-...] Maya delivers '...'. [...]
  Robot intones '...'. [...] Co-host reacts '...'.`

## Examples in this folder

- `examples/voice-test.json` — minimal 2-clip voice-ref smoke test
- `examples/news-broll.json` — 3 b-roll cutaways with VO
- `examples/news-segment-full.json` — full 10-clip segment

## Asset pack contents

`news-show-v1` includes a 3-character sakuga cast (Maya/Trip/FAQ-9000)
plus voice WAVs, environment refs, and example composites. See
`asset-pack.manifest.json` for per-file purpose. Two of the composites
(`comp_china`, `comp_dhs`) are shipped as positive AND cautionary
examples — `comp_china` triggers Seedance copyright filter on Trump
likeness; `comp_dhs` is the right pattern (no portrait, just a Capitol
illustration + caption).
