# Character Asset Workflow

End-to-end recipe for producing a **transparent character video asset** — a
3D-rendered character performing an alive idle animation, keyed against pure
green to a VP8-alpha webm, ready to drop into any composition (web hero,
title card, motion graphic, after-effects comp, etc).

## Inputs

- A character reference image (illustrated/stylized only — photoreal faces
  hit Seedance E005 moderation; see memory `project_seedance_ref_videos_face_moderation`)
- A short creative brief (outfit, vibe, pose, expression beats)
- `.env` with `GOOGLE_API_KEY` and `REPLICATE_API_TOKEN`

## Outputs

- `runs/<slug>/images/<id>.png` — full-body or framed 3D render on green
- `runs/<slug>/videos/<id>.mp4` — 10s alive idle on green
- `<asset>.webm` — VP8-alpha keyed transparent video (drop-in compositable)
- `<asset>-poster.png` — keyed still poster for fallback / loading state

---

## Steps

### 1. Build the timeline

Two clips: a centered render, then a face-focused idle starting from that
render as `first_frame`.

```json
{
  "version": 1,
  "project": { "name": "Character Asset" },
  "defaults": {
    "video": { "model": "seedance-2.0", "resolution": "720p", "aspect_ratio": "16:9", "duration": 10, "generate_audio": false },
    "image": { "model": "nano-banana-pro", "aspect_ratio": "16:9", "resolution": "2K", "output_format": "png" }
  },
  "tracks": [{
    "id": "visuals", "type": "video",
    "clips": [
      {
        "id": "char-render",
        "source": {
          "type": "image",
          "prompt": "A waist-up medium portrait of <CHARACTER>, stylized 3D video-game character render style. She is positioned DEAD CENTER in the 16:9 frame with GENEROUS empty space on every side. Comfortable headroom above her head (~15% of frame height of clear space above). Generous breathing room on the left and right (~20-25% of frame width of clear background each side) so her hair has plenty of space to sweep. Framed from mid-torso up to well above her head. <DETAILS>. Pure chroma-green background (#00B140), flat solid green with no shadows or gradients. Soft neutral key light with gentle rim, no cast shadow on the background. Crisp PBR materials, anime-influenced 3D style. 16:9 framing.",
          "reference_images": ["path/to/character-ref.png"]
        }
      },
      {
        "id": "char-idle",
        "source": {
          "type": "video",
          "prompt": "A LOCKED-OFF waist-up medium shot of <CHARACTER> performing an engaging, expressive video-game character-select idle animation. The camera is completely stationary — NO orbit, NO rotation, NO zoom, NO pan, NO dolly. Her body stays in roughly the same position the entire shot. ALL of the animation lives in her face and head: she casually scans her surroundings, eyes tracking softly to her left then drifting back to camera, then glancing up briefly, then to her right, then settling back on the viewer. She blinks naturally and at uneven intervals. Her brow raises once with quiet curiosity. She gives a slow confident smirk that grows for a beat before easing back. A single deliberate wink at the camera around the middle of the shot. Her lips part subtly as if breathing. Between glances her head tilts just a little, chin lifting and lowering. Subtle micro-shifts of weight cause her shoulders to roll gently and her chest visibly rises and falls with breath. Long hair drifts and sways with soft breeze physics, fabric ripples gently. Confident, alive, relaxed, magnetic — like a fighting-game character watching the player choose them. Pure chroma-green background (#00B140), flat solid green with no shadows or gradients.",
          "duration": 10,
          "quality": "high",
          "first_frame": { "ref": "char-render" }
        }
      }
    ]
  }],
  "output": { "format": "mp4" }
}
```

> See memory `project_replicate_2000_char_prompt_truncation` — the video
> prompt above is ~1.7k chars; tail beats survive. Don't push past 2000.

### 2. Run the pipeline

```bash
python pipeline.py --timeline-file <name>.json --stage final
```

Resume on edits with `--resume-dir runs/<slug>` so the existing render is
reused while only the video re-renders.

### 3. Key + crop + encode to alpha webm

```bash
python scripts/key_character.py runs/<slug>/videos/char-idle.mp4 \
    --out assets/char-idle.webm \
    --poster assets/char-idle-poster.png
```

This script is the proven recipe: bbox-scans every frame, crops to the
character's full sweep + 50px padding, keys each frame with PIL
green-excess + threshold-snap, despills, and encodes to a VP8-alpha webm
with libvpx.

---

## Critical rules — different from other workflows

### Prompting

- **Repeat "locked camera" forcefully.** Seedance defaults to subtle
  camera drift even when not asked. Use ALL CAPS: `LOCKED-OFF ... NO
  orbit, NO rotation, NO zoom, NO pan, NO dolly`. Then describe the
  body as stationary too.
- **Frame for breathing room.** When the prompt asks for "centered with
  generous headroom and ~20-25% side breathing room", the character's
  hair sweep won't clip during head turns or look-arounds. A tighter
  frame WILL clip during animation — Seedance moves more than the still
  suggests.
- **Pure green specifically (`#00B140`).** Don't say "green screen" —
  Seedance interprets that loosely (sometimes adds shadows or
  gradients). Hex literal in the prompt + "flat solid green with no
  shadows or gradients" is the reliable phrasing.
- **Use `first_frame`, not `reference_images`, for locked-start idles.**
  `first_frame` locks the opening pose to the exact render. With
  `reference_images` Seedance may re-pose between the render and the
  video.
- **Always use `quality: high` on the clip itself, not in defaults.**
  The `defaults.video.quality` field is silently dropped by the parser
  ("Unknown field 'quality' at 'defaults.video.quality'" warning); the
  video then runs at `basic`. Put `quality: "high"` on the source.

### Keying

- **Don't use ffmpeg's `chromakey` filter for stylized/anime content.**
  It uses YUV chrominance distance which over-flags dark hair, shadowed
  fabric, and any pixel with a green-blue undertone — turning the
  character into a soft semi-transparent ghost. Use PIL green-excess
  (`g − max(r,b)`) instead — only flags pixels where green is genuinely
  the dominant channel.
- **Threshold-snap the alpha.** After computing the soft matte, snap
  alpha > 200 → 255, alpha < 40 → 0. Keeps a 1-2px feathered outline,
  makes everything else fully solid. Without this the character looks
  see-through on a colored background.
- **Bbox-scan EVERY frame, not sampled timestamps.** When seek-stepping
  with `video.currentTime = t`, some encodes return the same keyframe
  for nearby seeks → identical bbox readings → you'll under-crop and
  clip the character's hair on the widest frames. Decode all 240
  frames as PNG and union their bboxes.
- **Pad the crop ~50px on every side.** Seedance has subtle frame-drift
  even on locked-camera shots; tight crops chop the silhouette during
  motion peaks.

### Encoding

- **VP9 alpha is unreliable.** Even with `-pix_fmt yuva420p
  -auto-alt-ref 0 -metadata:s:v:0 alpha_mode=1`, this ffmpeg build
  drops the alpha block during muxing — the file plays opaque. **Use
  VP8 alpha (`libvpx`) instead.** It's older but the alpha format is
  battle-tested in Chrome/Firefox/Safari.

  ```bash
  ffmpeg -framerate 24 -i keyed/%04d.png \
      -c:v libvpx -pix_fmt yuva420p -auto-alt-ref 0 \
      -b:v 2000k -an out.webm
  ```

- **APNG and HEVC-with-alpha are both worse trade-offs** for web/comp
  use: APNG is huge (50MB+ for 10s), HEVC alpha is Safari-only.

---

## Cost

Per asset (one render + one 10s `seedance-2.0` 720p high-quality video):

| Item | Approx |
|---|---|
| `nano-banana-pro` 2K image (with reference) | $0.04 |
| `seedance-2.0` 720p `quality: high` 10s with `first_frame` | $1.70 |
| **Total** | **~$1.74** |

Drafts: switch video to `seedance-2.0-fast` at 480p (~$0.06/s) — useful
for iterating prompt language before committing to a final 720p render.

---

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Character looks see-through on dark bg | ffmpeg `chromakey` over-flagged hair/shadows | Re-key in PIL with green-excess + threshold-snap |
| Hair clips off the side during spin/turn | Bbox detected from a small sample of frames | Scan every frame, union bboxes, then crop with padding |
| Webm plays opaque (no transparency) | VP9 alpha dropped by some ffmpeg builds | Re-encode with `libvpx` (VP8) instead of `libvpx-vp9` |
| Idle has subtle camera orbit/zoom | Seedance default drift | Repeat "LOCKED-OFF ... NO orbit, NO rotation, NO zoom, NO pan, NO dolly"; describe body as stationary |
| Video runs at `basic` quality | `quality` set in `defaults.video.*` | Move `quality: "high"` onto the clip's `source` |
| Reference photo of real person flagged | Seedance E005 photoreal moderation | Use a stylized/illustrated source, or describe character in text only |

---

## Files in this workflow

- `pipeline.py` (project root) — the standard mograph runner
- `scripts/key_character.py` — bbox-scan + PIL key + VP8-alpha encode
- `docs/character-asset/CLAUDE.md` — agent-facing crib sheet
