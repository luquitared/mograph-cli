# format-rip — agent notes

Read this when the user wants to recreate or remix the *structural template*
of a reference video (TikTok / IG reel / YouTube short) — the beats, sound
effects, text overlays, camera moves. For visual style ripping, see
`docs/style-rip/`. For full strategy, see this folder's `README.md`.

## How to drive this workflow

```bash
# 1. Pull source + extract frames
yt-dlp -o "runs/style-packs/<slug>/source.%(ext)s" "<url>"
ffmpeg -i runs/style-packs/<slug>/source.mp4 -vf "fps=1/1.2" -q:v 2 \
  runs/style-packs/<slug>/frames/frame_%02d.jpg

# 2. Structural analysis (Gemini)
python scripts/format_describe.py \
  runs/style-packs/<slug>/source.mp4 \
  runs/style-packs/<slug>/format.json

# 3. (If format has on-screen text) generate overlay PNGs via batch_image_gen.py + gpt-image-2

# 4. Build timeline using format.json's remix_template + beat timestamps + key_sfx

# 5. Validate, run, push pack
python scripts/timeline_validate.py my-timeline.json
python scripts/run.py my-timeline.json
python scripts/asset_pack_push.py runs/style-packs/<slug> <slug> --prefix style-packs
```

## Defaults — pick these

- Source: anything yt-dlp can pull. Most public IG/TikTok/YouTube reels work without auth.
- Frame extraction: `fps=1/1.2` (a frame ~every 1.2s). Adjust for source length; aim for 8–12 frames.
- Format analysis model: `gemini-3.1-pro-preview` (what `scripts/format_describe.py` uses).
- Generation: `seedance-2.0-fast` at 480p for testing, `seedance-2.0` at 720p for finals.
- **Aspect ratio: match the source.** Vertical reels → `9:16`. Don't default to 16:9.
- **Ask the user about source audio.** Format-rip's source mp4 has a load-bearing audio bed (the format-defining sfx + music). Before writing the timeline, ask: *"Use the source's original audio (muxed in post via ffmpeg), or let Seedance generate fresh audio?"* Default to **source audio muxed in post** when the format has `audio_design.key_sfx[].load_bearing: true` cues — those are the format. Set `generate_audio: false` and after the run: `ffmpeg -i final/video_concat.mp4 -i runs/style-packs/<slug>/source.mp4 -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -shortest <output>.mp4`
- **Multi-clip consistency:** see root `CLAUDE.md`. For format-rip, generate the character anchor with the source's frames as refs so it lands in-style.

## Critical rules

- **Replicate truncates prompts at 2000 chars.** Anything past is dropped silently. `timeline_validate.py` flags >1900 (warn), >2000 (error). For multi-beat formats with sfx cues, you'll be near the limit — trim style/setting prose first.
- **Read format.json's `remixable.fixed[]` list before remixing.** Those elements MUST be preserved or it's no longer the same format.
- **Read `audio_design.key_sfx[].load_bearing: true` cues.** Those sfx ARE the format. Describe them in the prompt with exact timestamps.
- **Don't use real-human source video as `reference_videos`.** E005 moderation fires on photoreal humans (memory note exists). Describe motion in the prompt instead.
- **For on-screen text, pre-render overlay PNGs via `gpt-image-2`.** Don't ask Seedance to render text from scratch — it garbles.

## Style trade-off you'll hit

A high-contrast modern 2D overlay PNG outweighs source style frames in Seedance's reference averaging, pulling output toward "modern clean." Two ways out:

- **Drop the overlay ref**, let Seedance approximate text. Style stays clean. Text gets uglier. Plan ffmpeg-overlay in post for the final.
- **Generate the overlay PNG in a style matching the source** (pixelated for PS1, hand-drawn for cartoon). Stays cohesive but more work.

The two examples in `examples/` show this trade-off side by side.

## Composing with style-rip

Format from one pack, visual style from another:

```json
"reference_images": [
  "runs/style-packs/<style-source>/frames/frame_02.jpg",
  "runs/style-packs/<style-source>/frames/frame_04.jpg",
  "runs/style-packs/<style-source>/frames/frame_06.jpg"
]
```

Use the FORMAT source's `format.json` to scaffold the prompt; pass the STYLE source's frames as `reference_images`. See `examples/healthy-lifestyle-remix.json`.

## What format-rip does NOT solve well today

- **Frame-accurate sfx timing** — Seedance approximates. For exact ding/boom hits, plan ffmpeg post-overlay.
- **Crisp text overlays without style drift** — pre-rendered overlays solve text but cost style fidelity. Real solution: ffmpeg post-overlay (not built yet).
- **Multi-step physical action chains** that span >5 seconds — Seedance can do them but works better with shorter, imperative beat descriptions. Long elaborate action descriptions → ignored.

The "real" format-rip pipeline (silent video + ffmpeg compositing) hasn't been built yet. Today's workflow is single-pass Seedance with pre-rendered overlay refs. Documented in README §7.

## Examples

- `examples/dating-after-25-clone.json` — exact clone of `ig-DXsns8PpVlj` source, restyled to PS1 low-poly. No overlay ref → cleaner PS1 style; text rendered by Seedance with one minor typo. Demonstrates the "drop overlay ref" path.
- `examples/healthy-lifestyle-remix.json` — same format, swapped scenario (gym lie → hot dog at 7-Eleven), modern overlay ref. Demonstrates clean text + style drift trade-off.

## Format packs available

See `format-pack.manifest.json` for the registry of packs with `format.json`. Pull with `python scripts/asset_pack_pull.py <id> --prefix style-packs`.
