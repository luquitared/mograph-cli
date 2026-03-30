# Script Format Reference

Define video structure, narration, and visual prompts in JSON.

## Required Format

```json
{
  "script_title": "Video Title",
  "subject": "Topic description",
  "brand_name": "Brand Name",
  "reference_images": ["images/moodboard.png", "images/logo.png"],
  "scenes": [
    {
      "scene_number": 1,
      "scene_type": "Hook",
      "narrator": "Opening narration text",
      "scene_overview": "What this scene accomplishes",
      "visuals": [
        {
          "concept_name": "Visual concept name",
          "image_prompt": "AI-optimized static image prompt",
          "animation_prompt": "Motion description"
        }
      ]
    }
  ]
}
```

## Key Fields

- `reference_images`: Array of paths to reference images (up to 14). These drive the visual style of generated images. Include moodboards, style guides, color palettes, logos, etc.
- `scenes`: Array of scenes with `narrator` text, `scene_overview`, and `visuals`
- `visuals`: Each has `concept_name`, `image_prompt`, and `animation_prompt`

## Multi-Clip Scenes

Define multiple visuals per scene that get concatenated under a single narration block:

```json
{
  "scene_number": 1,
  "narrator": "Once upon a time, in a land far away.",
  "visuals": [
    {
      "concept_name": "once_upon",
      "image_prompt": "Text 'Once upon' centered on screen",
      "animation_prompt": "Text fades in from black",
      "duration": 2,
      "alternatives": [
        {
          "image_prompt": "Text 'Once upon' in bold serif font",
          "animation_prompt": "Text slides in from left"
        }
      ]
    },
    {
      "concept_name": "a_time",
      "image_prompt": "Text 'a time' with mystical background",
      "animation_prompt": "Background sparkles, text glows",
      "duration": 2
    }
  ]
}
```

| Field          | Description                                                      |
| -------------- | ---------------------------------------------------------------- |
| `duration`     | Seconds for this clip (defaults to `--video-seconds` if omitted) |
| `alternatives` | Optional backup versions for review/selection                    |

Pipeline flow: Generate all clips -> concatenate primary clips -> overlay narration -> apply timing mode.

## Reference Images (Style Control)

Include up to **14 reference images** and reference them by filename in prompts:

```json
{
  "script_title": "My Video",
  "reference_images": [
    "images/brand/logo.png",
    "images/brand/style_guide.jpg",
    "images/characters/mascot.png"
  ],
  "scenes": [...]
}
```

Use in `image_prompt` for style/color reference, logo integration, transformations, product showcase:

```json
{
  "image_prompt": "A data dashboard using the color scheme and visual style from style_guide.jpg, modern infographic layout"
}
```

## Narrator Timing & Word Count

The narrator speaks at approximately **2 words per second (WPS)**. ENSURE THAT YOU COUNT THE WORDS SO THAT TIMING OF THE AUDIO MATCHES THE GENERATED VIDEO LENGTH!

| Video Duration | Target Word Count |
|----------------|-------------------|
| 4 seconds      | ~8 words          |
| 6 seconds      | ~12 words         |
| 8 seconds      | ~16 words         |

### Timing Modes (`--timing-mode`)

- `audio-match` (default): Speed up audio to match video duration
- `video-match`: Speed up video to match audio, or freeze last frame if audio is longer

### Fine-Tuning with `--video-buffer-ms`

- `--video-buffer-ms 500` adds 0.5 seconds to each video
- `--video-buffer-ms -200` subtracts 0.2 seconds from each video
