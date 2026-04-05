# Supported Models

Reference for all generation models available in the timeline format.

---

## Video Models

### Veo 3.1 (`veo-3.1`)

Google's highest-quality video generation model.

| Parameter | Values | Default |
|-----------|--------|---------|
| `duration` | 4, 6, 8 seconds | 6 |
| `resolution` | `"720p"`, `"1080p"` | `"720p"` |
| `generate_audio` | `true`/`false` | `true` |
| `negative_prompt` | any string | `null` |
| `seed` | any int | `null` |

- **When to use:** Final renders where quality matters most.
- **Limitations:** Slowest of the Veo family. Higher cost per clip.

### Veo 3.1 Fast (`veo-3.1-fast`)

Faster variant of Veo 3.1 with slightly lower quality. Default video model.

| Parameter | Values | Default |
|-----------|--------|---------|
| `duration` | 4, 6, 8 seconds | 6 |
| `resolution` | `"720p"` only | `"720p"` |
| `generate_audio` | `true`/`false` | `true` |
| `negative_prompt` | any string | `null` |
| `seed` | any int | `null` |

- **When to use:** Iteration and drafts, or when 720p is sufficient.
- **Limitations:** 720p only. Quality slightly below `veo-3.1`.

### Veo 3.1 Lite (`veo-3.1-lite`)

Lightweight Veo variant. Audio is always generated regardless of the `generate_audio` setting.

| Parameter | Values | Default |
|-----------|--------|---------|
| `duration` | 4, 6, 8 seconds | 6 |
| `resolution` | `"720p"`, `"1080p"` | `"720p"` |
| `generate_audio` | ignored (always on) | — |
| `negative_prompt` | any string | `null` |
| `seed` | any int | `null` |

- **When to use:** Quick previews, bulk generation, cost-sensitive workflows.
- **Limitations:** `generate_audio: false` is ignored (validator emits a warning).

### Kling v3 Omni (`kling-v3`)

Alternative video model from Kuaishou via Replicate.

| Parameter | Values | Default |
|-----------|--------|---------|
| `duration` | model-determined | — |
| `resolution` | `"720p"`, `"1080p"` | `"720p"` |
| `generate_audio` | `true`/`false` | `true` |
| `negative_prompt` | any string | `null` |
| `seed` | any int | `null` |

- **When to use:** When Veo produces undesirable results, or for stylistic variety.
- **Limitations:** Duration is not constrained to 4/6/8 like Veo models.

### Seedance 2.0 (`seedance-2.0`)

ByteDance's video generation model via MuAPI. Supports text-to-video and image-to-video (via `first_frame`).

| Parameter | Values | Default |
|-----------|--------|---------|
| `duration` | any integer (seconds) | 5 |
| `aspect_ratio` | `"16:9"`, `"9:16"`, `"4:3"`, `"3:4"` | `"16:9"` |
| `quality` | `"basic"`, `"high"` | `"basic"` |
| `first_frame` | ref, generate, or path | `null` |

- **When to use:** Image-to-video workflows, stylistic variety, or when Veo/Kling results are unsatisfactory.
- **Limitations:** No `last_frame` support (only `first_frame` for I2V). No native audio generation. No `negative_prompt` or `seed`. Requires `MUAPI_API_KEY` env var (not Replicate). `"high"` quality produces 2K resolution output.

**Example (text-to-video):**
```json
{
  "type": "video",
  "prompt": "A cinematic shot of a futuristic city with neon lights",
  "model": "seedance-2.0",
  "duration": 5,
  "quality": "high"
}
```

**Example (image-to-video with DAG reference):**
```json
{
  "type": "video",
  "prompt": "Camera slowly pans across the scene",
  "model": "seedance-2.0",
  "first_frame": { "ref": "my-image-asset" },
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
| `reference_images` | array of paths/URLs | `[]` |
| `safety_filter_level` | e.g. `"block_only_high"` | `"block_only_high"` |

- **When to use:** Generating first-frame images for video clips, standalone stills, exploration candidates.
- **Limitations:** Subject to Replicate API rate limits. Reference images must be accessible URLs or local paths.

---

## TTS Models

### Gemini TTS (`gemini-2.5-flash-tts`)

Text-to-speech via Google Gemini Flash TTS (actual API model: `gemini-2.5-flash-preview-tts`).

| Parameter | Values | Default |
|-----------|--------|---------|
| `voice` | See voice list below | `"Kore"` |
| `voice_prompt` | any string | `null` |

**Available Voices:**

Achernar, Achird, Algenib, Algieba, Alnilam, Aoede, Autonoe, Callirrhoe, Charon, Despina, Enceladus, Erinome, Fenrir, Gacrux, Iapetus, Kore, Laomedeia, Leda, Orus, Puck, Pulcherrima, Rasalgethi, Sadachbia, Sadaltager, Schedar, Sulafat, Umbriel, Vindemiatrix, Zephyr

**Voice Prompt:**

The `voice_prompt` field accepts natural language instructions for tone and delivery style:
```json
{
  "voice": "Kore",
  "voice_prompt": "Speak in a calm, educational tone. Enunciate clearly."
}
```

- **When to use:** All narration generation. Supports per-clip voice and style overrides.
- **Limitations:** The validator enforces the voice list above. Misspelled voice names produce an error with a "did you mean?" suggestion.

---

## Cost Considerations

Generation costs vary by model and parameters:

| Model | Relative Cost | Notes |
|-------|--------------|-------|
| `veo-3.1` | High | Use for final renders |
| `veo-3.1-fast` | Medium | Good default for iteration |
| `veo-3.1-lite` | Low | Cheapest video option |
| `kling-v3` | Medium | Alternative provider |
| `seedance-2.0` | Medium | MuAPI, basic/high quality |
| `nano-banana-pro` | Low | Fast image generation |
| `gemini-2.5-flash-tts` | Low | Per-character pricing |

Use `veo-3.1-fast` (the default) during development, then switch to `veo-3.1` for final renders by updating the `defaults.video.model` field.
