# Timeline Format Reference

Complete field-by-field documentation for the timeline JSON format (version 1).

Fields prefixed with `_` (e.g. `_comment`) are silently ignored by the parser and can be used for inline documentation.

---

## Top-Level

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `version` | `int` | Yes | — | Must be `1`. |
| `project` | `Project` | Yes | — | Project metadata. |
| `defaults` | `Defaults` | No | `{}` | Default parameters for each source type. |
| `assets` | `object` | No | `{}` | Named reusable source objects keyed by ID. |
| `tracks` | `Track[]` | Yes | — | Ordered list of tracks (at least one). |
| `output` | `Output` | No | `{}` | Output format and mix settings. |

## Project

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | `string` | Yes | — | Project name (non-empty). |
| `description` | `string` | No | `null` | Project description. |
| `aspect_ratio` | `string` | No | `"16:9"` | Global aspect ratio. |
| `resolution` | `string` | No | `"720p"` | Global resolution. |

## Defaults

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `video` | `VideoDefaults` | No | `{}` | Default video generation params. |
| `image` | `ImageDefaults` | No | `{}` | Default image generation params. |
| `tts` | `TTSDefaults` | No | `{}` | Default TTS params. |

### VideoDefaults

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | `string` | `"veo-3.1-fast"` | Video model. One of: `veo-3.1`, `veo-3.1-fast`, `veo-3.1-lite`, `kling-v3`. |
| `duration` | `int` | `6` | Clip duration in seconds. Veo models: `4`, `6`, or `8`. |
| `generate_audio` | `bool` | `true` | Whether to generate audio with the video. |
| `aspect_ratio` | `string` | `"16:9"` | Aspect ratio. |
| `resolution` | `string` | `"720p"` | Resolution. Model-specific constraints apply. |
| `verify` | `bool\|string` | `null` | Enable verification for all video clips. See [Verification](#verification). |

### ImageDefaults

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | `string` | `"nano-banana-pro"` | Image model. |
| `aspect_ratio` | `string` | `"16:9"` | Aspect ratio. |
| `resolution` | `string` | `"2K"` | Image resolution. |
| `output_format` | `string` | `"png"` | `"png"` or `"jpg"`. |
| `reference_images` | `string[]` | `[]` | Paths or URLs to reference images. |
| `safety_filter_level` | `string` | `"block_only_high"` | Safety filter level. |
| `verify` | `bool\|string` | `null` | Enable verification for all image clips. See [Verification](#verification). |

### TTSDefaults

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `voice` | `string` | `"Kore"` | Voice name (see models.md for full list). |
| `model` | `string` | `"gemini-2.5-flash-tts"` | TTS model. |
| `voice_prompt` | `string` | `null` | Optional style/tone instructions for the voice. |

## Track

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | `string` | Yes | — | Unique ID. Must match `[a-zA-Z0-9_-]+`. |
| `type` | `string` | Yes | — | One of: `video`, `narration`, `audio`. |
| `clips` | `Clip[]` | Yes | — | Ordered list of clips (at least one). |
| `volume` | `float` | No | `null` | Track volume `0.0`–`1.0`. Only meaningful for audio tracks. |

## Clip

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | `string` | Yes | — | Unique ID. Must match `[a-zA-Z0-9_-]+`. |
| `source` | `Source` | Yes | — | Media source (see Source Types below). |
| `start_time` | `float` | No | `null` | Explicit start time in seconds. |
| `duration` | `float \| "auto"` | No | `"auto"` | Duration in seconds, or `"auto"` for source-determined. |
| `fit_to` | `string` | No | `null` | ID of another clip to match duration to. |
| `fit_method` | `string` | No | `"speed"` | How to adjust when fitting: `"speed"`. |
| `buffer_ms` | `float` | No | `0.0` | Buffer time in milliseconds between clips. |
| `label` | `string` | No | `null` | Optional human-readable label. |

---

## Source Types

Every source has a `type` discriminator field. Valid types: `image`, `video`, `tts`, `file`, `silence`, `still`.

### ImageSource (`type: "image"`)

Generates an image via Replicate Nano Banana Pro.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `"image"` | Yes | — | Source type discriminator. |
| `prompt` | `string` | Yes | — | Image generation prompt. |
| `reference_images` | `string[]` | No | from defaults | Paths or URLs to reference images. |
| `model` | `string` | No | from defaults | Image model name. |
| `aspect_ratio` | `string` | No | from defaults | Aspect ratio. |
| `resolution` | `string` | No | from defaults | Resolution. |
| `output_format` | `string` | No | from defaults | `"png"` or `"jpg"`. |
| `safety_filter_level` | `string` | No | from defaults | Safety filter level. |
| `candidates` | `object[]` | No | `null` | Array of prompt variant overrides for exploration. |
| `select` | `int` | No | `null` | 1-based index into candidates to use. |
| `verify` | `bool\|string` | No | from defaults | Post-generation verification. See [Verification](#verification). |

### VideoSource (`type: "video"`)

Generates a video clip via Veo 3.1 or Kling v3.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `"video"` | Yes | — | Source type discriminator. |
| `prompt` | `string` | Yes | — | Video generation prompt. |
| `first_frame` | `string \| Ref \| Generate \| null` | No | `null` | First frame input: file path/URL, ref, or inline generation. |
| `last_frame` | `string \| Ref \| Generate \| null` | No | `null` | Last frame input (same types as first_frame). |
| `model` | `string` | No | from defaults | One of: `veo-3.1`, `veo-3.1-fast`, `veo-3.1-lite`, `kling-v3`. |
| `duration` | `int \| "auto"` | No | from defaults | Duration in seconds. Veo: `4`, `6`, or `8`. |
| `aspect_ratio` | `string` | No | from defaults | Aspect ratio. |
| `resolution` | `string` | No | from defaults | Resolution. See model constraints. |
| `generate_audio` | `bool` | No | from defaults | Generate audio with video. |
| `negative_prompt` | `string` | No | `null` | Negative prompt (what to avoid). |
| `seed` | `int` | No | `null` | Random seed for reproducibility. |
| `candidates` | `object[]` | No | `null` | Prompt variant overrides for exploration. |
| `select` | `int` | No | `null` | 1-based index into candidates. |
| `verify` | `bool\|string` | No | from defaults | Post-generation verification. See [Verification](#verification). |

### TTSSource (`type: "tts"`)

Generates speech audio via Gemini TTS.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `"tts"` | Yes | — | Source type discriminator. |
| `text` | `string` | Yes | — | Text to synthesize. |
| `voice` | `string` | No | from defaults | Voice name (see models.md for list). |
| `voice_prompt` | `string` | No | from defaults | Style/tone instructions. |
| `model` | `string` | No | from defaults | TTS model. |
| `candidates` | `object[]` | No | `null` | Voice/style variant overrides. |
| `select` | `int` | No | `null` | 1-based index into candidates. |

### FileSource (`type: "file"`)

References an existing file on disk or URL.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `"file"` | Yes | — | Source type discriminator. |
| `path` | `string` | Yes | — | File path (relative to timeline file) or URL. |
| `start` | `float` | No | `null` | Start time in seconds for segment extraction. |
| `end` | `float` | No | `null` | End time in seconds for segment extraction. |

### SilenceSource (`type: "silence"`)

Generates silence of a specified duration.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `"silence"` | Yes | — | Source type discriminator. |
| `duration` | `float` | Yes | — | Duration in seconds (minimum 0.1s). |

### StillSource (`type: "still"`)

Creates a video clip from a static image held for a duration.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `"still"` | Yes | — | Source type discriminator. |
| `image` | `string \| Ref` | Yes | — | Image path/URL or ref to an image-producing source. |
| `duration` | `float` | Yes | — | Duration in seconds. |

---

## Ref

References another clip or asset's output. Used in `first_frame`, `last_frame`, and `still.image`.

```json
{ "ref": "clip-id", "extract": "last_frame" }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ref` | `string` | Yes | ID of the target clip or asset. |
| `extract` | `string` | No | What to extract: `"first_frame"`, `"last_frame"`, or `"audio"`. If omitted, uses the full output. |

**Constraints:**
- `extract: "first_frame"`, `"last_frame"`, or `"audio"` requires the target to be a video source.
- Without `extract`, the target must be an image, video, or still source.

## Generate

Inline generation instruction. Embeds a source definition directly in a `first_frame` or `last_frame` field.

```json
{ "generate": { "type": "image", "prompt": "..." } }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `generate` | `Source` | Yes | A complete source object to generate inline. |

**Constraints:**
- Maximum nesting depth: 2 levels.

---

## Output

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `format` | `string` | No | `"mp4"` | Output format. |
| `variants` | `OutputVariants` | No | `{}` | Which output variants to produce. |
| `narration_volume` | `float` | No | `1.0` | Narration volume `0.0`–`1.0`. |
| `sfx_volume` | `float` | No | `0.3` | SFX/ambient volume `0.0`–`1.0`. |
| `audio_mix` | `object` | No | `null` | Per-track volume overrides. |

### OutputVariants

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `narration_only` | `bool` | `true` | Produce a narration-only variant. |
| `narration_sfx` | `bool` | `true` | Produce a narration + SFX variant. |
| `images_only` | `bool` | `false` | Produce an images-only variant. |

---

## Validation Constraints

### IDs
- Must match `[a-zA-Z0-9_-]+`
- Must be unique across all assets and clips (flat namespace)

### Input Bounds
- Max tracks: 50
- Max clips per track: 200
- Max total clips: 500
- Max candidates per source: 20
- Max prompt size: 10 KB
- Max file size: 1 MB (timeline JSON itself)
- Max generate nesting: 2 levels

### Model-Specific Constraints

| Model | Durations | Resolutions |
|-------|-----------|-------------|
| `veo-3.1` | 4, 6, 8 | 720p, 1080p |
| `veo-3.1-fast` | 4, 6, 8 | 720p only |
| `veo-3.1-lite` | 4, 6, 8 | 720p, 1080p |
| `kling-v3` | — | 720p, 1080p |

---

## Verification

Post-generation quality check using Gemini vision. After an image or video is generated, the output is sent to Gemini to verify it matches the generation prompt. If verification fails, the clip is regenerated (up to 3 total attempts). If all attempts fail, the last result is used anyway and the failure is logged.

### The `verify` field

Available on `ImageSource`, `VideoSource`, `ImageDefaults`, and `VideoDefaults`.

| Value | Behavior |
|-------|----------|
| `true` | Check prompt adherence: "Does this output match the prompt?" |
| `"custom criteria"` | Check prompt adherence + custom criteria |
| `false` | Skip verification (overrides default) |
| omitted / `null` | Inherit from defaults (or skip if no default) |

### Setting a default

Enable verification for all video clips:

```json
"defaults": {
  "video": {
    "model": "veo-3.1-fast",
    "verify": true
  }
}
```

Individual clips can override:

```json
{
  "id": "vid-2",
  "source": {
    "type": "video",
    "prompt": "...",
    "verify": "The optic nerve must be clearly visible as a distinct pathway."
  }
}
```

Or disable for a specific clip:

```json
{
  "id": "vid-3",
  "source": {
    "type": "video",
    "prompt": "...",
    "verify": false
  }
}
```

### How it works

1. Clip is generated normally (image or video)
2. If `verify` is enabled, the output is sent to Gemini 2.5 Flash vision
3. For images: the image file is sent directly
4. For videos: a frame is extracted from the middle of the clip
5. Gemini evaluates against the generation prompt (and custom criteria if provided)
6. **Pass** → clip proceeds to assembly
7. **Fail** → clip is regenerated and verified again (up to 3 total attempts)
8. **All attempts fail** → last result is used anyway

### Output

Results are written to `runs/<run>/verification.json`:

```json
{
  "vid-1": {
    "passed": true,
    "attempts": 1,
    "reason": "Video shows a translucent brain with blue-highlighted occipital lobe as requested.",
    "used_anyway": false
  },
  "vid-2": {
    "passed": false,
    "attempts": 3,
    "reason": "Optic nerve is present but signals appear as a continuous stream rather than discrete pulses.",
    "used_anyway": true
  }
}
```

### Requirements

- `GEMINI_API_KEY` or `GOOGLE_API_KEY` environment variable must be set
- `ffmpeg` / `ffprobe` must be available for video frame extraction
- If no API key is available, verification is skipped with a warning
