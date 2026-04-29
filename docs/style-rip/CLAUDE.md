# style-rip — agent notes

Read this when the user wants to take a reference video (TikTok, IG reel,
YouTube short) and generate new content in its visual style. For the full
workflow, see `README.md`.

## How to drive this workflow

```bash
# 1. Pull source
yt-dlp -o "runs/style-packs/<slug>/source.%(ext)s" "<url>"

# 2. Extract frames (~1.5s interval)
ffmpeg -i runs/style-packs/<slug>/source.mp4 -vf "fps=1/1.5" -q:v 2 \
  runs/style-packs/<slug>/frames/frame_%02d.jpg

# 3. Gemini style analysis
python scripts/style_describe.py \
  runs/style-packs/<slug>/source.mp4 \
  runs/style-packs/<slug>/style.json

# 4. Read style.json. Use prompt_template + 3-5 frames in your timeline.

# 5. Validate + run + (optional) push pack
python scripts/timeline_validate.py my-timeline.json
python scripts/run.py my-timeline.json
python scripts/asset_pack_push.py runs/style-packs/<slug> <slug> --prefix style-packs
```

## Defaults — pick these

- Source: anything yt-dlp can pull. Most public IG/TikTok/YouTube
  reels work without auth.
- Frame extraction: `fps=1/1.5` (one frame every 1.5s). Adjust for
  source duration; aim for 5–10 representative frames.
- Style description model: `gemini-3.1-pro-preview` (this is what
  `scripts/style_describe.py` uses).
- Generation: `seedance-2.0-fast` at 480p for testing,
  `seedance-2.0` at 720p for finals.
- **Aspect ratio: match the source.** Vertical reels → `9:16`;
  cinematic sources → `16:9`. Don't default-cargo-cult `16:9`.

## The pattern

A `style-pack` is three things: source.mp4, frames/, style.json. That's
it. No characters, no voices baked in — those are workflow concerns
that happen ON TOP of a style pack.

When generating in a ripped style, every video clip's
`reference_images` should include 3–5 frames from the pack. The prompt
must include the `prompt_template` from style.json verbatim — that's
the highest-leverage line.

## Critical rules

- **Read style.json before writing prompts.** The `what_to_avoid` list
  is non-decorative — it lists modern render terms ("anti-aliasing",
  "PBR shading", "ray tracing") that will *break* a retro-style rip if
  layered on top. Strip those from your prompt.
- **Describe characters in medium-compatible terms.** A "scruffy guy"
  is not enough — say "blocky polygonal head, pixelated face texture,
  simple low-poly hair" if the source is low-poly 3D. The medium has to
  match or the character will look like a foreign object pasted onto
  the style.
- **Frame count: 3–5 in `reference_images`.** Pick for visual variety
  (one wide, one close-up, one with the iconic motif). More than 5 just
  averages them and the specific signal weakens.
- **Aspect ratio matches source.** A 9:16 reel rendered as 16:9 looks
  like a cropped game cutscene, not native content.

## Voice constraints

Style packs do NOT include voice samples — voice consistency is a
separate concern. For the first clip, describe voice characteristics
verbatim in the prompt (tone, accent, pace, raspiness, age). Then if
the user wants character continuity, extract the generated voice via
`scripts/analyze_news_clip.py` + `ffmpeg`, save as a wav, and pass it
in `reference_audios` on subsequent clips (which then requires you to
also pass `reference_images`, satisfied by the style frames).

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Result is "almost" the style but too polished | Default modern render assumptions | Add the source's `what_to_avoid` items as negative-leaning prompt language |
| Character looks foreign / over-detailed | Describing character without medium-specific language | Use blocky/polygonal/pixelated/claymation terminology that matches the source |
| Cinematic landscape on a vertical UGC source | aspect_ratio left at 16:9 default | Override per-clip to `9:16` for selfie / handheld / UGC sources |
| Generated clip ignores the style entirely | Reference frames not passed, OR too many style descriptors fighting the frames | Verify `reference_images` has 3–5 frame paths; trim prompt to the `prompt_template` + scene description, no extra style modifiers |

## Examples

- `examples/news-anchor-test.json` — 5s, low-poly news anchor, 16:9
- `examples/stoner-selfie-test.json` — 8s, UGC selfie monologue, 9:16

Both use the `ig-DW2FRgojpMa` style pack (PS1 low-poly nightscape).

## Style-rip vs the other workflows

- **vs `news-video`**: news-video has a fixed cast and recurring set;
  style-rip is single-clip generation in a ripped aesthetic. If the user
  wants a 2+ clip narrative with style consistency, run style-rip first
  to lock the look, then build characters/voices on top using the
  news-video pattern.
- **vs `narration-explainer`**: narration-explainer is one visual per
  TTS beat and uses `first_frame.generate`. Style-rip uses
  `reference_images` instead and one self-contained scene per clip.
- **vs `music-video`**: music-video drives clip boundaries from a song
  analysis. Style-rip is style-first; if you also want music-driven
  cuts, run music-video and pass style-pack frames as
  `reference_images` on each clip.
