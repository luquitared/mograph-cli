# Supported Models

Reference for all generation models available in the timeline format.

---

## Video Models

### Seedance 2.0 Fast (`seedance-2.0-fast`)

Default video model. Faster, cheaper variant of Seedance 2.0 — trades some quality for speed. Same inputs and capabilities. Best for drafts, iteration, and high-volume pipelines.

| Parameter | Values | Default |
|-----------|--------|---------|
| `duration` | integer seconds `4`–`15`, or `-1` for auto | 5 |
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
- **Limitations:** Same as Seedance 2.0 — `reference_images` and `first_frame` are mutually exclusive. No `negative_prompt`. `duration < 4` is rejected server-side with E006 — for shorter playback, generate at `>=4` and trim via float `clip.duration` at assembly.

### Seedance 2.0 (`seedance-2.0`)

ByteDance's higher-quality multimodal video generation model. Same inputs as Fast variant. Use for final renders when quality matters.

| Parameter | Values | Default |
|-----------|--------|---------|
| `duration` | integer seconds `4`–`15`, or `-1` for auto | 5 |
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

### Nano Banana 2 (`nano-banana-2`)

Burst-mode image generation via the Gemini API directly (bypasses Replicate). Same underlying model (Gemini 3.1 Flash Image Preview) as `nano-banana-pro` but configured for maximum throughput: minimal thinking, IMAGE-only response.

| Parameter | Values | Default |
|-----------|--------|---------|
| `aspect_ratio` | `1:1`, `4:3`, `3:4`, `16:9`, `9:16`, `3:2`, `2:3`, `4:5`, `5:4`, `21:9`, `1:4`, `4:1`, `1:8`, `8:1` | `"1:1"` |
| `resolution` | `"512"`, `"1K"`, `"2K"`, `"4K"` | `"512"` |
| `output_format` | `"png"`, `"jpg"` | `"png"` |
| `reference_images` | array of local file paths | `[]` |

- **When to use:** High-throughput exploration where speed matters more than resolution. Requires `GOOGLE_API_KEY`.

### GPT Image 2 (`gpt-image-2`)

OpenAI's `openai/gpt-image-2` model via Replicate. Strong at photoreal composition and text rendering; supports reference images for editing/composing.

| Parameter | Values | Default |
|-----------|--------|---------|
| `aspect_ratio` | `"1:1"`, `"3:2"`, `"2:3"` | `"1:1"` |
| `output_format` | `"webp"`, `"png"`, `"jpeg"` | `"webp"` |
| `reference_images` | array of paths/URLs or `{"ref": "clip_id"}` | `[]` |
| `quality` | `"low"`, `"medium"`, `"high"`, `"auto"` | `null` |
| `background` | `"auto"`, `"opaque"` | `null` |
| `output_compression` | integer `0`–`100` (applies to webp/jpeg) | `null` |
| `moderation` | `"auto"`, `"low"` | `null` |

- **When to use:** Photoreal scenes with precise composition or on-image text; editing/composing via `reference_images`.
- **Limitations:** Does not support transparent backgrounds. Only three aspect ratios (1:1, 3:2, 2:3). `resolution` and `safety_filter_level` are ignored.

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

**Fast vs Standard savings:** 14-24% cheaper across the board.

**Strategy guide:**
- **Drafts/iteration:** `seedance-2.0-fast` at `480p` ($0.06/s) — the default
- **Final renders:** Switch `defaults.video.model` to `seedance-2.0` at `720p` ($0.17/s)
- **Video chaining drafts:** `seedance-2.0-fast` at `480p` with `reference_videos` ($0.11/s)
- **Video chaining finals:** `seedance-2.0` at `720p` with `reference_videos` ($0.29/s)
