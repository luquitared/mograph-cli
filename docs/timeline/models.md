# Supported Models

Reference for all generation models available in the timeline format.

---

## Video Models

### Seedance 2.0 Fast (`seedance-2.0-fast`)

Default video model. Faster, cheaper variant of Seedance 2.0 — trades some quality for speed. Same inputs and capabilities. Best for drafts, iteration, and high-volume pipelines.

| Parameter | Values | Default |
|-----------|--------|---------|
| `duration` | any integer seconds, or `-1` for auto | 5 |
| `resolution` | `"480p"`, `"720p"` | `"480p"` |
| `aspect_ratio` | `"16:9"`, `"4:3"`, `"1:1"`, `"3:4"`, `"9:16"`, `"21:9"`, `"adaptive"` | `"16:9"` |
| `generate_audio` | `true`/`false` | `true` |
| `seed` | any int | `null` |
| `quality` | `"basic"`, `"high"` | `"basic"` |
| `first_frame` | ref, generate, or path | `null` |
| `last_frame` | ref, generate, or path (requires first_frame) | `null` |
| `reference_images` | up to 9 images; strings, URLs, or `{"ref": "clip_id"}` | `[]` |
| `reference_videos` | up to 3 videos (max 15s total); strings, URLs, or `{"ref": "clip_id"}` | `[]` |
| `reference_audios` | up to 3 audio files (max 15s total) | `[]` |

- **When to use:** Default for all video generation. Cheapest at 480p ($0.06/s). Use for drafts and iteration.
- **Limitations:** Same as Seedance 2.0 — `reference_images` and `first_frame` are mutually exclusive. No `negative_prompt`.

### Seedance 2.0 (`seedance-2.0`)

ByteDance's higher-quality multimodal video generation model. Same inputs as Fast variant. Use for final renders when quality matters.

| Parameter | Values | Default |
|-----------|--------|---------|
| `duration` | any integer seconds, or `-1` for auto | 5 |
| `resolution` | `"480p"`, `"720p"` | `"480p"` |
| `aspect_ratio` | `"16:9"`, `"4:3"`, `"1:1"`, `"3:4"`, `"9:16"`, `"21:9"`, `"adaptive"` | `"16:9"` |
| `generate_audio` | `true`/`false` | `true` |
| `seed` | any int | `null` |
| `quality` | `"basic"`, `"high"` | `"basic"` |
| `first_frame` | ref, generate, or path | `null` |
| `last_frame` | ref, generate, or path (requires first_frame) | `null` |
| `reference_images` | up to 9 images; strings, URLs, or `{"ref": "clip_id"}` | `[]` |
| `reference_videos` | up to 3 videos (max 15s total); strings, URLs, or `{"ref": "clip_id"}` | `[]` |
| `reference_audios` | up to 3 audio files (max 15s total) | `[]` |

- **When to use:** Final renders where quality matters. Switch from `seedance-2.0-fast` by updating `defaults.video.model`.
- **Limitations:** `reference_images` and `first_frame` (image) are mutually exclusive. No `negative_prompt`.

**Seedance examples:**

```json
// Text-to-video (cheapest: fast + 480p + no video refs = $0.06/s)
{
  "type": "video",
  "prompt": "A cinematic shot of a futuristic city with neon lights",
  "duration": 5,
  "resolution": "480p"
}
```

```json
// Video-to-video chaining (pipe previous clip output as reference)
{
  "type": "video",
  "prompt": "Continue the scene. [Video1] The camera slowly pulls back to reveal the full cityscape.",
  "reference_videos": [{"ref": "previous-clip"}],
  "duration": 5
}
```

```json
// Image-to-video with character references
{
  "type": "video",
  "prompt": "[Image1] is the main character. They walk through a neon-lit market.",
  "reference_images": [{"ref": "character-ref"}],
  "duration": 5
}
```

### Veo 3.1 Lite (`veo-3.1-lite`)

Google's lightweight Veo variant. Audio is always generated regardless of the `generate_audio` setting.

| Parameter | Values | Default |
|-----------|--------|---------|
| `duration` | 4, 6, 8 seconds | 6 |
| `resolution` | `"720p"`, `"1080p"` | `"720p"` |
| `generate_audio` | ignored (always on) | — |
| `negative_prompt` | any string | `null` |
| `seed` | any int | `null` |

- **When to use:** When you need Veo quality with built-in audio, or 1080p output.
- **Limitations:** `generate_audio: false` is ignored. ~$0.15/s at 720p.

---

## Image Models

### Nano Banana Pro (`nano-banana-pro`)

Image generation via Replicate (Google Gemini 3.1 Flash Image Preview).

| Parameter | Values | Default |
|-----------|--------|---------|
| `aspect_ratio` | e.g. `"16:9"`, `"1:1"`, `"9:16"` | `"16:9"` |
| `resolution` | e.g. `"2K"` | `"2K"` |
| `output_format` | `"png"`, `"jpg"` | `"png"` |
| `reference_images` | array of paths/URLs or `{"ref": "clip_id"}` | `[]` |
| `safety_filter_level` | e.g. `"block_only_high"` | `"block_only_high"` |

- **When to use:** Generating first-frame images for video clips, standalone stills, exploration candidates.
- **Reference image chaining:** Use `{"ref": "clip_id"}` to feed one image generation's output as a reference into the next.

---

## TTS Models

### Gemini TTS (`gemini-2.5-flash-tts`)

Text-to-speech via Google Gemini Flash TTS.

| Parameter | Values | Default |
|-----------|--------|---------|
| `voice` | See voice list below | `"Kore"` |
| `voice_prompt` | any string | `null` |

**Available Voices:**

Achernar, Achird, Algenib, Algieba, Alnilam, Aoede, Autonoe, Callirrhoe, Charon, Despina, Enceladus, Erinome, Fenrir, Gacrux, Iapetus, Kore, Laomedeia, Leda, Orus, Puck, Pulcherrima, Rasalgethi, Sadachbia, Sadaltager, Schedar, Sulafat, Umbriel, Vindemiatrix, Zephyr

---

## Cost Comparison

| Model | Resolution | Input | Cost/sec | ~Seconds/$10 |
|-------|-----------|-------|----------|--------------|
| `seedance-2.0-fast` | 480p | text/image | **$0.06** | **~166s** |
| `seedance-2.0-fast` | 480p | video refs | $0.11 | ~90s |
| `seedance-2.0-fast` | 720p | text/image | $0.13 | ~76s |
| `seedance-2.0-fast` | 720p | video refs | $0.22 | ~45s |
| `seedance-2.0` | 480p | text/image | $0.07 | ~142s |
| `seedance-2.0` | 480p | video refs | $0.13 | ~76s |
| `seedance-2.0` | 720p | text/image | $0.17 | ~58s |
| `seedance-2.0` | 720p | video refs | $0.29 | ~34s |
| `veo-3.1-lite` | 720p | — | ~$0.15 | ~66s |

**Fast vs Standard savings:** 14-24% cheaper across the board.

**Strategy guide:**
- **Drafts/iteration:** `seedance-2.0-fast` at `480p` ($0.06/s) — the default
- **Final renders:** Switch `defaults.video.model` to `seedance-2.0` at `720p` ($0.17/s)
- **Video chaining drafts:** `seedance-2.0-fast` at `480p` with `reference_videos` ($0.11/s)
- **Video chaining finals:** `seedance-2.0` at `720p` with `reference_videos` ($0.29/s)
