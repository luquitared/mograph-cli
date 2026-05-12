# video-clone — agent notes

Read this when the user wants a 1:1 reproduction of a reference video
(TikTok / IG reel / YT short) — same style, beats, cuts, and audio. For
remixes (swap content, keep beats), use `docs/format-rip/`. For
style-only theft, use `docs/style-rip/`.

## How to drive

```bash
SLUG=ig-<reel-id>
PROJECT="<Source Title> Clone"

# 1. Pull source + dense frames + audio
yt-dlp -o "runs/style-packs/$SLUG/source.%(ext)s" "<url>"
ffmpeg -i runs/style-packs/$SLUG/source.mp4 -vf "fps=1/0.5" -q:v 2 \
  runs/style-packs/$SLUG/frames/frame_%03d.jpg
ffmpeg -i runs/style-packs/$SLUG/source.mp4 -vn -c:a copy \
  runs/style-packs/$SLUG/source_audio.m4a

# 2. Analyze structure + style
python scripts/format_describe.py runs/style-packs/$SLUG/source.mp4 runs/style-packs/$SLUG/format.json
python scripts/style_describe.py  runs/style-packs/$SLUG/source.mp4 runs/style-packs/$SLUG/style.json

# 3. Init project, build timeline (see README §2)
python scripts/init_project.py "$PROJECT"

# 4. Validate, run, mux source audio
python scripts/timeline_validate.py runs/<slug>/<slug>.json
python scripts/run.py runs/<slug>/<slug>.json
ffmpeg -i runs/<slug>/final/video_concat.mp4 -i runs/style-packs/$SLUG/source_audio.m4a \
  -map 0:v -map 1:a -c:v copy -shortest \
  runs/<slug>/final/video_clone.mp4
```

## Defaults — pick these

- Frame extraction: **`fps=1/0.5`** (every 0.5s). Higher density than
  format-rip's 1.2s — clone work needs close frame matches at every beat
  boundary.
- Generation: **`seedance-2.0`** at **720p**, 16:9 or 9:16 matching source.
  This is the one workflow where the higher fidelity tier earns its cost.
- `generate_audio: false` everywhere. Source audio is muxed in step 4.

## Style control

Use the same pattern as the repo-root README's "Locking Style with a Mood
Board" — paste `style.json:prompt_template` into
`defaults.video.prompt_prefix`. Don't re-explain it here.

For clone, prefer **first_frame + last_frame** for action timing over
**reference_images** for style continuity, because:

1. `first_frame` and `reference_images` are mutually exclusive
   (validator-enforced).
2. Beat-boundary timing is more load-bearing for clone than for rip.
3. The prompt_prefix carries style well enough on its own; the frames
   carry composition.

Use `reference_images` only for clips where action is static-ish and
texture continuity matters more than precise timing.

## Hard constraints

- Seedance `duration` is integer **4–15** (or `-1` for auto). Beats <4s
  must be merged with neighbors or generated-then-trimmed (see README §3).
- `first_frame` ⊥ `reference_images`. `last_frame` is fine alongside
  `reference_images`, but in practice for clone you want both anchors.
- Replicate truncates prompts at 2000 chars. With prompt_prefix eating
  200–500 chars, keep beat descriptions terse — frames carry composition.
- Photoreal-human style frames trip E005. `first_frame` single-use
  sometimes passes where `reference_images` doesn't; otherwise drop
  visual refs and lean on prompt_prefix text alone.

## Critical rules

- **Source audio always.** Don't regenerate audio with `reference_audios`
  — mux the original m4a in the post step. This is the workflow's
  defining choice.
- **Match source aspect ratio.** Read it with ffprobe before setting
  defaults; don't let 16:9 leak in for a 9:16 reel.
- **One clip per beat** unless `<4s` forces a merge. Note merges in the
  clip's `label` field so a future trimmer can find them.
- **Validate before running.** `timeline_validate.py` catches WPS
  overflow, prompt length, bad ref paths, and the first_frame ⊥
  reference_images conflict.

## Where this fails today

- **Frame-accurate cut transitions** — int-second clip durations vs
  float-second source boundaries. Expect ±0.5s slop per cut. Mitigate
  with ffmpeg trim/pad before concat, or accept the slop.
- **Lipsync** — Seedance can't lipsync to muxed audio. Best paths: frame
  source so faces aren't dialogue-focused, or accept the mismatch
  (viewers register audio sync more than lip sync).
- **Camera-move fidelity** — Seedance interprets "slow push-in" loosely.
  Document divergences as you find them in README §9.

## Test target

`ig-Czq5Miosz9u` (https://www.instagram.com/reel/Czq5Miosz9u/) — first
clone candidate. Once it works end-to-end, push the pack and add an
entry to `docs/format-rip/format-pack.manifest.json` flagged as having
both `format.json` and `style.json` (so format-rip and style-rip can
both consume it too).

## Examples

None yet — needs the test run on `ig-Czq5Miosz9u` to author the first
working timeline. Document divergences from source in this folder once
the run completes.
