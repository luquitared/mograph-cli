# Format-Rip Workflow

Take a reference video (TikTok, IG reel, YouTube short) and extract its
*structural template* — beats, sound effects, text overlay positions,
camera moves, archetype — so you can re-fill it with new content. Sister
workflow to `style-rip`, which captures the visual look. Format-rip
captures the *shape* of how content is delivered.

## When to use this workflow

- A specific format/trope you've seen on social media and want to remix
  (setup-punchline meme, expectation-vs-reality, before/after, POV
  reaction, tutorial, etc.)
- The structure (beats, timing, sfx, text overlays) is more important
  than the visual style
- You want to recreate the original beat-for-beat or swap out elements
  (subject, setting, dialogue) while keeping the format recognizable

If you want to mimic a *visual look* and don't care about the structure,
use `docs/style-rip/`. The two workflows compose — start with style-rip
to lock the look, then format-rip to lock the beats.

## Inputs

- A URL or local file of the source video (anything yt-dlp can pull)
- `.env` with `GOOGLE_API_KEY` (Gemini structural analysis) and
  `REPLICATE_API_TOKEN` (Seedance generation)

## Outputs

- A pack: `source.mp4` + `frames/` + `format.json` (and optionally
  `overlays/` with text/graphic overlay PNGs)
- Pushed to GCS at `gs://$GCS_OUTPUT_BUCKET/style-packs/<slug>/`
- One or more generated remix clips

---

## Quick start

```bash
# 1. Pull source
yt-dlp -o "runs/style-packs/<slug>/source.%(ext)s" "<url>"

# 2. Frames
ffmpeg -i runs/style-packs/<slug>/source.mp4 -vf "fps=1/1.2" -q:v 2 \
  runs/style-packs/<slug>/frames/frame_%02d.jpg

# 3. Structural analysis (NOT style — see docs/style-rip/ for that)
python scripts/format_describe.py \
  runs/style-packs/<slug>/source.mp4 \
  runs/style-packs/<slug>/format.json

# 4. Read format.json. Note the beats[], audio_design.key_sfx, and the
#    remix_template field.

# 5. Generate text overlay reference images via gpt-image-2 if the
#    format has on-screen text (top captions + iMessage bubbles etc.)

# 6. Build the timeline. Use the remix_template as your scaffold,
#    timestamp the beats inside the prompt, fill in your new content.

# 7. Validate, run
python scripts/timeline_validate.py my-timeline.json
python scripts/run.py my-timeline.json

# 8. (Optional) Push the pack to mograf.ai for reuse
mograf pack push runs/style-packs/<slug> --kind style --slug <slug>
```

---

## 1. The format.json file

`scripts/format_describe.py` runs Gemini 3.1 Pro on the source video
and returns a structured analysis with these load-bearing fields:

- **`archetype`** — what category of internet video this is (setup-punchline meme, before/after, POV reaction, etc.)
- **`beats[]`** — time-ordered structural moments. Each has `start`, `end`, `label`, `what_happens`, `audio_event`, `text_overlay`, `camera`. **The most useful field for remixing.**
- **`persistent_text_overlays[]`** — text that stays on screen the whole video (e.g. a "Dating after 25" header)
- **`audio_design.key_sfx[]`** — load-bearing sfx with timestamps. The `load_bearing: true` ones MUST be preserved or the format breaks.
- **`format_signature`** — Gemini's one-line "what makes this recognizable as this format"
- **`remixable.swappable[]` / `remixable.fixed[]`** — explicit guidance on what you can change vs. must keep
- **`remix_template`** — concrete instructions for re-filling the format with new content. Paste-and-modify scaffold.

Read all of it before designing your remix. The `fixed` list is non-decorative — touching those breaks the format.

## 2. Designing a remix

### 2a. The three-axis swap

Most remixes change one or more of:

- **Subject** (who's in the video)
- **Scenario** (the topic / setup)
- **Style** (visual aesthetic — composes with `docs/style-rip/`)

Keeping all of `audio_design.key_sfx[].load_bearing: true`, the beat
timing, and the camera/shot type fixed is what makes it read as the
same format.

### 2b. Per-clip prompt structure

```
STYLE: <one or two sentences. If composing with a style pack, paste the
style pack's prompt_template here.>

SHOT: <camera framing — usually copy from format.json beats[].camera>

SUBJECT: <character description in style-compatible terms>

PERSISTENT OVERLAY (full <X>s, top center): <verbatim header text>,
<font/color/stroke from format.json:persistent_text_overlays>

[<beat 1 start>s-<beat 1 end>s] BEAT 1: <action description>. AUDIO:
<sfx with timestamp if load-bearing>.

[<beat 2 start>s-<beat 2 end>s] BEAT 2: <action description>. AUDIO:
<sfx if any>.

[<beat 3 start>s-<beat 3 end>s] BEAT 3 — PUNCHLINE: <action
description>. AUDIO: at <timestamp>s, <load-bearing sfx>.
```

See `examples/dating-after-25-clone.json` and
`examples/healthy-lifestyle-remix.json` for working timelines built from
the `ig-DXsns8PpVlj` format pack.

## 3. Text overlays — pre-render don't ask Seedance

For formats with on-screen text (captions, iMessage bubbles, lower
thirds), **don't ask Seedance to render the text from scratch** — the
model approximates and produces garbled text or wrong layout. Instead:

1. Generate the overlay graphic as a PNG with `gpt-image-2` (best at
   text rendering). Build a small manifest and run
   `scripts/batch_image_gen.py` against it.
2. Pass the overlay PNG as one of the `reference_images` in your
   timeline. Seedance composes it into frames.

**Caveat — the trade-off we hit:** a high-contrast modern overlay PNG
can outweigh the source's style references in Seedance's averaging,
pulling the output style toward "modern clean." Two ways out:

- **Skip the overlay ref entirely** and let Seedance approximate the
  text. Style stays clean. Text gets ugly. Plan to ffmpeg-overlay the
  real graphic in post.
- **Generate the overlay PNG in a style consistent with the source**
  (pixelated for PS1, hand-drawn for cartoon, etc.) so it doesn't fight
  the style refs.

See `examples/dating-after-25-clone.json` (no overlay ref, cleaner
style) vs `examples/healthy-lifestyle-remix.json` (modern overlay ref,
style drifted modern).

## 4. SFX — describe in prompt with timestamps

Seedance can be cued to produce sfx at specific timestamps via prompts:
`AUDIO: at exactly 4.5s, a single LOUD deep-bass 'Vine boom' impact`.
This works *approximately* — the model usually puts something
percussive near the timestamp but doesn't fire on the exact frame.

For frame-accurate sfx (which is what makes most format-rip jokes
land), the only reliable answer is post-process compositing: generate
silent video, mix in real sfx samples via ffmpeg at exact timestamps.
That's a separate pipeline — see "Path forward" below.

## 5. Critical Replicate constraint — 2000 char prompts

**Replicate silently truncates prompts past 2000 characters.** Beat
descriptions get clipped and the model improvises everything past the
cut. Symptom: your last beat doesn't happen.

`scripts/timeline_validate.py` flags prompts >1900 chars (warn) and
>2000 chars (error). Run it before every generation.

For format-rip prompts with multiple beats and detailed action chains,
you'll usually be near the limit. Trim:

- Style/setting prose — references carry it
- Adjective stacks ("loud dramatic deep-bass impact" → "loud bass impact")
- Repeated reminders — pick one place to say "header stays full duration"

## 6. Composing format-rip + style-rip

To get the format from one source and the visual style from another,
build the timeline with refs from both packs:

```json
"reference_images": [
  "runs/style-packs/<style-source>/frames/frame_02.jpg",
  "runs/style-packs/<style-source>/frames/frame_04.jpg",
  "runs/style-packs/<style-source>/frames/frame_06.jpg"
]
```

…and use the format source's `format.json` to scaffold the prompt's
beat structure. The style frames pull the look; the prompt's beat
descriptions pull the structure.

`examples/healthy-lifestyle-remix.json` does exactly this: format from
`ig-DXsns8PpVlj` (Dating after 25), style from `ig-DW2FRgojpMa` (PS1
low-poly).

## 7. Path forward — real format-rip pipeline

Single-pass Seedance gets us 80% of the way to format-rip. The last 20%
(frame-accurate sfx, crisp text overlays without style drift) needs
post-processing:

1. Generate base video silently with style refs only
2. ffmpeg-overlay the modern overlay PNG at known regions
3. Mix sfx samples (iMessage ding, Vine boom) at exact timestamps
4. Re-encode

Not built yet. The next iteration of this workflow will add a
`format_compose.py` helper that takes a silent base + overlays + a
timing spec and composites the final.

## 8. Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Last beat doesn't happen | Prompt past 2000 chars, Replicate truncated | Trim prompt; check with `scripts/timeline_validate.py` |
| Output style is "modern clean" instead of source style | Overlay ref outweighed style frames | Drop overlay ref OR regen overlay in source-compatible style |
| Sfx fires near but not at the right timestamp | Seedance approximates audio cues | Plan for ffmpeg post-overlay |
| iMessage bubbles render with garbled text | Seedance can't reliably render text | Pre-render overlays as PNGs via gpt-image-2 |
| E005 moderation on `reference_videos` containing real humans | Photoreal-human refs trip Seedance | Drop the video ref; describe motion in prompt only |
| Text on screen is correct but action chain didn't execute | Multi-step physical actions (phone-down → bite, or phone-down → sleep) confuse Seedance in single clips | Describe action chain in shorter, more imperative beats; or split into multiple clips and concat |

## 9. Available format packs

See `format-pack.manifest.json` for the registry. Pull command:

```bash
mograf pack pull <pack-id>
```

| Pack | Format archetype | Use cases |
|---|---|---|
| `ig-DXsns8PpVlj` | Setup-punchline meme — text-vs-action contradiction | "Dating after [X]", "[Aspirational identity] in your 20s", any "I claim X but actually do Y" trope |
