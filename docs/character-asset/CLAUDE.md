# character-asset — agent notes

Read this when the user wants to produce a **transparent character video
asset** — a 3D-rendered character on chroma-green that gets keyed to an
alpha webm and dropped into something else (a web hero, a title card,
a motion comp). For the full recipe, see `README.md`.

## How to drive this workflow

```bash
# 1. Build the timeline (two clips: render + locked-camera idle)
#    Use first_frame chaining: render → idle.

# 2. Run
python pipeline.py --timeline-file <name>.json --stage final

# 3. Key + crop + encode to alpha webm
python scripts/key_character.py runs/<slug>/videos/<id>.mp4 \
    --out assets/<id>.webm --poster assets/<id>-poster.png
```

## Defaults

- Image: `nano-banana-pro`, 16:9, 2K, png
- Video: `seedance-2.0` (regular, NOT fast), 720p, 16:9, 10s,
  `quality: "high"` **on the clip source** (not defaults — silently dropped)
- Background: `#00B140` flat green, called out literally in prompt
- TTS: not used in this workflow

## Critical rules — different from other workflows

- **Repeat "LOCKED-OFF" in caps with explicit no-camera-motion list**
  (`NO orbit, NO rotation, NO zoom, NO pan, NO dolly`) — Seedance
  defaults to subtle drift otherwise.
- **Frame for breathing room** — describe `~15% headroom` and
  `~20-25% side margin` in the render prompt. Tight framing clips
  hair during head movement.
- **Use `first_frame`, not `reference_images`,** to lock the opening
  pose to the exact render.
- **Hex green literal in prompt** (`#00B140`) — saying "green screen"
  produces inconsistent shadows/gradients.
- **`quality: "high"` belongs on the clip source**, not in
  `defaults.video.*` (parser drops the latter silently).
- **Don't use ffmpeg's `chromakey` filter.** YUV chrominance distance
  over-flags dark hair / shadows on stylized characters. Use PIL
  green-excess via `scripts/key_character.py`.
- **Use VP8 alpha (`libvpx`), not VP9 alpha.** VP9 alpha block is
  unreliably muxed by some ffmpeg builds — file plays opaque.

## The creative brief is non-negotiable

Without an explicit brief from the user, agents default to whatever and
produce generic output. Ask before writing the timeline:

1. **Character.** Source reference image (illustrated only — photoreal
   faces hit E005). If they have one, get the path. If not, describe
   in text using slots: body type / hair / face / outfit /
   distinguishing feature.
2. **Pose / framing.** Waist-up centered (default for an asset hero) or
   full-body? What expression as the starting beat?
3. **Idle beats.** Which face/body micro-actions in the 10s loop —
   blinks, smirk, wink, brow raise, head tilt, weight shift, hair
   drift? Pick 3-5 specific beats; vague prompts give vague results.
4. **End use.** What surface will this composite onto — light bg, dark
   bg, video, motion graphic? Affects how aggressively to despill (more
   despill for light backgrounds, less for dark).
5. **Quality tier.** Draft (`seedance-2.0-fast`, 480p, ~$0.06/s) for
   prompt iteration, or final (`seedance-2.0`, 720p, `quality: high`,
   ~$0.17/s) once the brief is locked.

## Common pitfalls

See README.md "Common pitfalls" table — the four big ones are
ghost-character (need PIL key), hair-clipping (need full-frame bbox
scan), opaque-webm (need VP8 not VP9), and unwanted camera drift (need
ALL-CAPS no-camera-motion language).

## Files in this workflow

- `pipeline.py` (project root) — standard mograph runner
- `scripts/key_character.py` — bbox-scan + PIL key + VP8-alpha encode
