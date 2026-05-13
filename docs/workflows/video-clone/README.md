# Video-Clone Workflow

Reproduce a reference video as faithfully as Seedance allows — same style,
same beats, same cuts, same audio. Sister to `docs/format-rip/` (remix the
structure with new content) and `docs/style-rip/` (steal the look for new
content). Video-clone keeps everything; only the rendering engine changes.

## When to use this workflow

- Generation-quality benchmark: how close can Seedance get to a real clip?
- Reproducible test fixture for prompt / first-frame / ref-image experiments
- Validating that your `format.json` + `style.json` extractions are good
  enough to reconstruct the source

For *restyling* the source, use format-rip. For *stealing the look* into
new content, use style-rip. Use clone only when the goal is "make a
Seedance version of THIS exact clip."

## Inputs

- A URL or local file of the source video (anything yt-dlp can pull)
- `.env` with `GOOGLE_API_KEY` and `REPLICATE_API_TOKEN`
- `ffmpeg` and `yt-dlp` on PATH

## Outputs

- A pack at `runs/style-packs/<slug>/`: `source.mp4`, `frames/`,
  `format.json`, `style.json`, `source_audio.m4a`
- A clone timeline at `runs/<project-slug>/<project-slug>.json`
- The rendered clone at `runs/<project-slug>/final/video_clone.mp4`

---

## Quick start

```bash
SLUG=ig-<reel-id>
PROJECT="<Source Title> Clone"

# 1. Init project
python scripts/init_project.py "$PROJECT"

# 2. Pull source
yt-dlp -o "runs/style-packs/$SLUG/source.%(ext)s" "<url>"

# 3. Dense frame extraction (every 0.5s — denser than format-rip)
ffmpeg -i runs/style-packs/$SLUG/source.mp4 -vf "fps=1/0.5" -q:v 2 \
  runs/style-packs/$SLUG/frames/frame_%03d.jpg

# 4. Pull source audio (we mux this back in at the end — DON'T regenerate)
ffmpeg -i runs/style-packs/$SLUG/source.mp4 -vn -c:a copy \
  runs/style-packs/$SLUG/source_audio.m4a

# 5. Beat analysis (clip boundaries + per-beat what-happens)
python scripts/format_describe.py \
  runs/style-packs/$SLUG/source.mp4 \
  runs/style-packs/$SLUG/format.json

# 6. Style analysis (prompt_prefix text)
python scripts/style_describe.py \
  runs/style-packs/$SLUG/source.mp4 \
  runs/style-packs/$SLUG/style.json

# 7. Edit runs/<project-slug>/<project-slug>.json (see §2)

# 8. Validate, run
python scripts/timeline_validate.py runs/<project-slug>/<project-slug>.json
python scripts/run.py runs/<project-slug>/<project-slug>.json

# 9. Mux source audio onto the rendered video (the 1:1 unlock)
ffmpeg -i runs/<project-slug>/final/video_concat.mp4 \
       -i runs/style-packs/$SLUG/source_audio.m4a \
       -map 0:v -map 1:a -c:v copy -shortest \
       runs/<project-slug>/final/video_clone.mp4

# 10. (Optional) Push the pack (publishes to mograf.ai/packs)
mograf pack push runs/style-packs/$SLUG --kind style --slug $SLUG
```

---

## 1. The two-file source

Cloning consumes both:

- **`format.json`** — `beats[]` with `start`/`end`, `camera`, `what_happens`,
  `text_overlay`. Defines clip durations and per-beat prompts.
- **`style.json`** — visual descriptors. The `prompt_template` field goes
  verbatim into `defaults.video.prompt_prefix`.

Format-rip uses `format.json` for the structure and lets you swap the style.
Video-clone uses both, applies them faithfully, swaps nothing.

## 2. Building the clone timeline

Style control is the same `prompt_prefix` pattern as the repo-root
[Locking Style with a Mood Board](../../README.md#locking-style-with-a-mood-board)
section — paste `style.json:prompt_template` into
`defaults.video.prompt_prefix` and let it apply to every clip.

For each beat in `format.json`, emit one clip:

```json
{
  "id": "beat-1",
  "duration": <round(beat.end - beat.start), clamped to [4,15]>,
  "source": {
    "type": "video",
    "prompt": "<beat.what_happens, terse — the frames carry composition>",
    "first_frame": "runs/style-packs/<slug>/frames/<closest to beat.start>",
    "last_frame":  "runs/style-packs/<slug>/frames/<closest to beat.end>",
    "generate_audio": false
  }
}
```

> ⚠️ Seedance's `reference_images` and `first_frame` are **mutually
> exclusive** (validator enforces this). For 1:1 timing the frame anchors
> matter more than ref-image style anchoring, so for clone runs:
>   - **first_frame + last_frame** for action and composition
>   - **prompt_prefix** (from `style.json`) for the look
>
> Reserve the `reference_images` route only for clips where action timing
> matters less than texture continuity.

## 3. Beats shorter than 4s

Seedance won't accept `duration < 4` (errors with E006). Two options:

- **Merge** the short beat into a neighbor. Lose a cut, gain validity.
- **Generate at 4s, trim with ffmpeg.** Keeps the cut, costs an extra
  clip-second of compute, requires a post-step:
  ```bash
  ffmpeg -i clip.mp4 -t <real-duration> -c:v copy out.mp4
  ```

Note any merges in a clip `label` so the post-step trimmer can find them.

## 4. Prompt budget

Replicate truncates at 2000 chars. With `prompt_prefix` from `style.json`
(typically 200–500 chars) prepended to every clip, your per-clip beat
description budget shrinks. `scripts/timeline_validate.py` flags >1900
(warn) / >2000 (error). Keep beat descriptions terse — the first/last
frames already carry composition, the prefix already carries style; the
beat prompt only needs to describe the **action**.

## 5. Audio is the unlock

For a true 1:1, **mux the original audio** onto the generated video. Do
not regenerate sfx, music, or dialogue with Seedance — even with
`reference_audios` it won't be frame-accurate, and for clone work
"approximately right" defeats the purpose. Step 9 in Quick Start does
this with one ffmpeg command.

This is the biggest divergence from format-rip, which lives with
Seedance's approximate audio cuing. For clone we sidestep: same audio =
same dialogue + same sfx + same music, frame-accurate by construction.

## 6. Text overlays

If the source has on-screen text:

- **Persistent overlays** (header captions, lower thirds): pre-render
  with `gpt-image-2`, ffmpeg-overlay onto the final video.
- **Beat-anchored overlays** (iMessage bubbles that appear/disappear):
  same pre-render, then ffmpeg with
  `-filter_complex "[0:v][1:v]overlay=enable='between(t,a,b)'"`.

For clone work, do not rely on Seedance to render the source's text —
matching the source matters more than aesthetic cohesion, so take the
clean-text + ffmpeg-overlay path even though it costs you the in-engine
look. (Format-rip's §3 has the trade-off discussion.)

## 7. Aspect ratio and resolution

Match the source. Read with ffprobe:

```bash
ffprobe -v 0 -of csv=p=0 -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate \
  runs/style-packs/$SLUG/source.mp4
```

Set `defaults.video.aspect_ratio` and `defaults.video.resolution`
accordingly. Seedance supports `480p` and `720p`; pick **`720p`** for
clone work (this is the one workflow where the fidelity tier earns its
keep).

## 8. Test target

`ig-Czq5Miosz9u` (https://www.instagram.com/reel/Czq5Miosz9u/) is the
first test. Run Quick Start with `SLUG=ig-Czq5Miosz9u`, push the pack,
note divergences in §9 and iterate on prompt/frame strategies.

## 9. Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Beat clipped or extended | `duration` rounded incorrectly from float seconds | Round to nearest int, clamp `[4,15]`, trim/pad with ffmpeg post |
| Action doesn't match beat timing | `first_frame` too far from `beat.start`, or no `last_frame` | Re-extract frames at higher fps, pick the closest-to-boundary frame |
| Style drifts mid-clip | `prompt_prefix` too generic | Tighten `style.json:prompt_template`; or for that one clip, drop the frame anchors and use `reference_images` |
| Final out of sync with audio | Generated clip durations don't sum to source duration | Trim/pad each clip in ffmpeg before concat, then mux |
| E005 moderation on style frames | Photoreal humans in source frames | `first_frame` single-frame use often passes where `reference_images` doesn't; otherwise rely on `prompt_prefix` text only |
| Lipsync mismatch | Seedance can't lipsync to muxed audio | Frame the source so faces aren't featured, OR accept the mismatch (audio sync alone is what most viewers register) |

---

## What this workflow does NOT solve well today

- **Frame-accurate cut transitions.** Clip boundaries are integer seconds,
  source boundaries are float. Expect ±0.5s slop per cut.
- **Lipsync.** Out of scope. Use the source audio + a non-face-forward
  framing strategy.
- **Camera-move fidelity.** Seedance interprets "slow push-in" loosely.
  Document the divergences as you find them.

The honest position: clone gets you a recognizable Seedance reproduction
of the source, not a frame-by-frame match. The audio mux + dense frame
anchors close most of the gap that single-pass format-rip leaves open.
