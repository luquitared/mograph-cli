# Style-Rip Workflow

Take a reference video (a TikTok / Instagram reel / YouTube short / any
short clip) and generate new content in its visual style. Doesn't matter
if the source has people, cars, food, abstract shapes — the workflow
extracts the *look* and applies it to whatever scene the user wants.

## When to use this workflow

- The user found an aesthetic they like and wants more of it
- The visual style is the load-bearing part of the request, not the
  subject matter
- You need to mimic a specific render era (PS1 low-poly, early-2000s
  CGI, 1970s film, claymation) and improvising the prompt isn't getting
  there

If the user already has a fully-specified visual style in their head,
they don't need this workflow — just describe it directly in prompts.
This is for when there's a reference clip they want to imitate.

## Inputs

- A URL or local file of the source video (anything yt-dlp can pull,
  or any local mp4)
- `.env` with `GOOGLE_API_KEY` (Gemini style description) and
  `REPLICATE_API_TOKEN` (Seedance generation)

## Outputs

- A `style-pack` bundle: source.mp4 + frames/ + style.json
- Pushed to GCS at `gs://$GCS_OUTPUT_BUCKET/style-packs/<slug>/` for reuse
- One or more generated clips in the ripped style

---

## Quick start

```bash
# 1. Pull the source video
yt-dlp -o "runs/style-packs/<slug>/source.%(ext)s" "<url>"

# 2. Extract reference frames (every ~1.5s — adjust based on source duration)
ffmpeg -i runs/style-packs/<slug>/source.mp4 -vf "fps=1/1.5" -q:v 2 \
  runs/style-packs/<slug>/frames/frame_%02d.jpg

# 3. Generate structured style description with Gemini
python scripts/style_describe.py \
  runs/style-packs/<slug>/source.mp4 \
  runs/style-packs/<slug>/style.json

# 4. Eyeball 2-3 frames + read style.json to understand what you ripped

# 5. Build a timeline that uses the frames as reference_images and the
#    prompt_template from style.json as a STYLE: clause in the prompt
#    (see examples/stoner-selfie-test.json for the canonical pattern)

# 6. Generate, validate, run
python scripts/timeline_validate.py my-timeline.json
python scripts/run.py my-timeline.json

# 7. (Optional) Push the style-pack to GCS for reuse
python scripts/asset_pack_push.py runs/style-packs/<slug> <slug> --prefix style-packs
```

---

## 1. Pulling the source

Use `yt-dlp`. Most public Instagram/TikTok/YouTube reels work without
auth. If you hit a paywall or 403, you may need a cookies file (see
yt-dlp docs).

```bash
yt-dlp -o "runs/style-packs/<slug>/source.%(ext)s" --no-playlist "<url>"
```

The `<slug>` should be **stable and traceable** — for IG/TikTok the post
ID is fine (e.g. `ig-DW2FRgojpMa`). Don't rename packs after pushing them
to GCS.

## 2. Extracting frames

The right number of frames depends on the source's duration and
visual variety:

- 5–8 second source → 4–6 frames (every ~1s)
- 10–20 second source → 6–10 frames (every ~1.5–2s)
- Longer source → 10–15 frames spread evenly

Don't extract too many — Seedance accepts at most 9 reference images.
You typically pass 3–5 of the most stylistically representative ones to
each clip.

```bash
ffmpeg -i source.mp4 -vf "fps=1/1.5" -q:v 2 frames/frame_%02d.jpg
```

## 3. Gemini style description

`scripts/style_describe.py` uploads the source video to Gemini 3.1 Pro
and returns a structured JSON with:

- `name`, `tagline`, `medium`, `era_reference`
- `color_palette` (5–8 specific colors with usage notes)
- `linework_and_texture`, `lighting`, `composition`, `mood`
- `subjects_in_source` (what's actually shown)
- `what_to_keep` / `what_to_avoid`
- `prompt_template` — **the load-bearing field**: a concrete `STYLE:`
  clause you paste verbatim into image/video gen prompts

Read `style.json` end-to-end before designing your scene. The
`what_to_avoid` list flags things that would break the style — common
agent mistake is to layer modern style language on top (e.g. saying
"cinematic anti-aliasing" on a PS1 source defeats the whole point).

## 4. Designing scenes in the ripped style

Pattern that works:

```
STYLE: <paste prompt_template from style.json verbatim>. Match the
look in the reference images exactly — same polygon count, same
texture quality, same flat lighting, same palette.

SHOT TYPE: <selfie / wide establishing / handheld / locked-off / etc>

SUBJECT: <character or object — describe in terms compatible with the
ripped medium. For a PS1 source, describe the character as "low-poly 3D
character with blocky proportions, simple polygonal hair, pixelated face
texture with painted-on features">

SETTING: <where they are — if the source has specific iconic locations
like a 7-Eleven or a Bell payphone, callback to those for stronger style
transfer>

ACTION: [<timestamps>] <what happens, with dialogue>

AUDIO: <voice description, ambient, music>
```

The two examples in `examples/` are working timelines from the IG-PS1
pack:

- `news-anchor-test.json` — single anchor at a low-poly news desk, 5s
- `stoner-selfie-test.json` — UGC selfie monologue, 8s vertical, low-poly
  guy at the same 7-Eleven storefront from the source

Both render at $0.30–$0.50 each on `seedance-2.0-fast` 480p.

### Aspect ratio matters

If the source is vertical (most TikToks/reels) and you're generating
selfie/UGC content, set `aspect_ratio: "9:16"` on the video defaults. If
generating cinematic / news / wide content, override to `16:9`. Don't
just use the default 16:9 if the source style was built for 9:16 — it'll
look like a cropped video game cutscene instead of native UGC.

### Reference image count

Pass 3–5 frames as `reference_images`, picked for visual variety:

- One that shows the main "iconic" element (storefront, character,
  product)
- One with a different composition (close-up, wide, profile)
- One that shows the lighting/sky/atmosphere

More than 5 is usually noise — Seedance just averages them and the
specific signal weakens.

## 5. Reusing a pushed style pack

Once a pack is on GCS, anyone with bucket access can pull it:

```bash
python scripts/asset_pack_pull.py <slug> --prefix style-packs
# → runs/style-packs/<slug>/source.mp4, frames/, style.json
```

Reference paths in subsequent timelines just point at the local pulled
files (`runs/style-packs/<slug>/frames/frame_03.jpg`).

## 6. Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Generated clip is "almost" the right style but too clean / too modern | Default render assumptions overriding the style | Add stronger negative language from `style.json:what_to_avoid` to the prompt |
| Character in the clip looks too realistic / detailed for the source style | Prompt described the character without medium-specific language | If source is low-poly, describe character as "blocky polygonal face, pixelated texture"; if claymation, "visible thumbprints, hand-sculpted" |
| Style transfers but composition is wrong (cinematic when source was vertical UGC) | Aspect ratio mismatch | Override `aspect_ratio` per-clip to match the source's native shape |
| Voice doesn't match what the user asked for | Seedance picked a default voice | Describe voice characteristics in detail in the prompt (tone, accent, pace, raspiness) — voice ref WAVs are the next-step lock; this workflow is just style |
| Source has people but they barely appear | Style frames only have environments | Generate one character sheet first via gpt-image-2 with the style frames as refs, then use that sheet plus a couple style frames in subsequent clips |

## 7. Style packs available on GCS

| Pack ID | Style | Use cases |
|---|---|---|
| `ig-DW2FRgojpMa` | Retro PS1 low-poly nightscape | UGC, low-poly news, urban night scenes — see `style-pack.manifest.json` |

Pull command: `python scripts/asset_pack_pull.py <id> --prefix style-packs`
