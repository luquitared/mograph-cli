# Strategy E: Studio Workflow (UI-Driven)

## Core Concept

Every reference is a **single collage image** — not multiple files. This makes references predictable, compact, and easy to review. The video model is always **Seedance 2.0** with **15-second clips**.

## Collage Formats

### Moodboard Collage (1 image)
A grid of panels showing the visual style from different angles. User specifies grid size (e.g. 2x2, 2x3, 3x3).

**Prompt structure:**
```
"A [NxM] grid collage moodboard. [style description]. 
Top-left: [establishing wide shot]. Top-right: [close-up detail]. 
Bottom-left: [character study]. Bottom-right: [action scene].
Each panel separated by thin white borders. Landscape orientation, 16:9 aspect ratio."
```

Each panel should be labeled in the prompt (top-left, top-right, etc.) to give the model clear composition instructions.

### Character Sheet (1 image per character)
A uniform character turnaround sheet. Always the same layout:

**Prompt structure:**
```
"Character reference sheet for [name]. [style prefix].
3/4 front view (left), front facing view (center), profile view facing right (right).
[detailed appearance description].
Clean white/neutral background, full body, consistent proportions across all views.
Three views in a horizontal row, separated by thin borders. Landscape orientation, 16:9 aspect ratio."
```

This ensures every character sheet is predictable — 3 views, always the same order, always full body on a clean background.

### Environment Storyboard (1 image)
A collage showing the environment from multiple angles and times of day.

**Prompt structure:**
```
"Environment reference storyboard for [setting name]. [style prefix].
Top-left: wide establishing shot. Top-right: interior/close detail.
Bottom-left: different angle or time of day. Bottom-right: atmospheric mood shot.
[environment description]. No characters. 2x2 grid with thin borders. Landscape orientation, 16:9 aspect ratio."
```

### Scene Storyboard (1 image per 15-second clip)
A collage showing the key moments within a single 15-second clip. Includes timestamps.

**Prompt structure:**
```
"Storyboard for a 15-second scene: [scene label]. [style prefix].
Panel 1 (0:00-0:03): [opening action]. 
Panel 2 (0:04-0:07): [development]. 
Panel 3 (0:08-0:11): [climax]. 
Panel 4 (0:12-0:15): [resolution].
[characters involved]. 4 panels in a 2x2 grid with timestamps labeled below each panel.
Thin white borders between panels. Landscape orientation, 16:9 aspect ratio."
```

## Phases

### Phase 1: Moodboard
Generate **1 collage image** establishing the visual style.

**Timeline:**
```json
{
  "version": 1,
  "project": { "name": "<ProjectName>_Moodboard" },
  "defaults": {
    "image": { "model": "nano-banana-pro", "aspect_ratio": "16:9", "output_format": "png" }
  },
  "tracks": [{
    "id": "moodboard",
    "type": "video",
    "clips": [{
      "id": "moodboard",
      "label": "Style moodboard collage",
      "source": {
        "type": "image",
        "prompt": "A [NxM] grid collage moodboard. [STYLE DESCRIPTION]. Top-left: [PANEL 1]. Top-right: [PANEL 2]. Bottom-left: [PANEL 3]. Bottom-right: [PANEL 4]. Each panel separated by thin white borders. Landscape orientation, 16:9 aspect ratio."
      }
    }]
  }]
}
```

### Phase 2: Character Sheets + Environment
Generate **1 character sheet per character** and **1 environment storyboard**. All use the moodboard collage as `reference_images`.

**Timeline:**
```json
{
  "version": 1,
  "project": { "name": "<ProjectName>_Refs" },
  "defaults": {
    "image": { "model": "nano-banana-pro", "aspect_ratio": "16:9", "output_format": "png" }
  },
  "tracks": [{
    "id": "refs",
    "type": "video",
    "clips": [
      {
        "id": "<character-name>-sheet",
        "label": "<Character> character sheet",
        "source": {
          "type": "image",
          "prompt": "Character reference sheet for <NAME>. <STYLE PREFIX>. 3/4 front view (left), front facing view (center), profile view facing right (right). <APPEARANCE>. Clean neutral background, full body, consistent proportions. Three views in a horizontal row, separated by thin borders. Landscape orientation, 16:9 aspect ratio.",
          "reference_images": ["runs/<moodboard-run>/images/moodboard.png"]
        }
      },
      {
        "id": "env-storyboard",
        "label": "Environment storyboard",
        "source": {
          "type": "image",
          "prompt": "Environment reference storyboard for <SETTING>. <STYLE PREFIX>. Top-left: wide establishing shot. Top-right: interior detail. Bottom-left: different angle. Bottom-right: atmospheric mood. <ENV DESCRIPTION>. No characters. 2x2 grid with thin borders. Landscape orientation, 16:9 aspect ratio.",
          "reference_images": ["runs/<moodboard-run>/images/moodboard.png"]
        }
      }
    ]
  }]
}
```

### Phase 3: Story Arc (planning only)
Break the story into scenes. Each scene = **one 15-second Seedance clip**. For each scene, create:
- `label` — Scene title
- `prompt` — Video prompt (15 seconds of action)
- `firstFramePrompt` — A **storyboard collage** showing 4 key moments with timestamps

No pipeline runs in this phase.

### Phase 4: Scene Storyboard Images
Generate the **storyboard collage** for each scene. Each collage shows the 4 key moments of that 15-second clip with timestamps. **reference_images includes ALL refs**: moodboard + character sheets + environment storyboard.

**Timeline:**
```json
{
  "version": 1,
  "project": { "name": "<ProjectName>" },
  "defaults": {
    "video": { "model": "seedance-2.0", "generate_audio": false, "aspect_ratio": "16:9", "duration": 15 },
    "image": { "model": "nano-banana-pro", "aspect_ratio": "16:9" }
  },
  "tracks": [{
    "id": "visuals",
    "type": "video",
    "clips": [{
      "id": "scene-1",
      "label": "<Scene title>",
      "source": {
        "type": "video",
        "duration": 15,
        "prompt": "<15-second video prompt with continuous action>",
        "first_frame": {
          "generate": {
            "type": "image",
            "prompt": "Storyboard for a 15-second scene: <LABEL>. <STYLE PREFIX>. Panel 1 (0:00-0:03): <ACTION>. Panel 2 (0:04-0:07): <ACTION>. Panel 3 (0:08-0:11): <ACTION>. Panel 4 (0:12-0:15): <ACTION>. <CHARACTERS>. 2x2 grid with timestamps below each panel. Thin white borders. Landscape orientation, 16:9 aspect ratio.",
            "reference_images": [
              "runs/<refs-run>/images/<char1>-sheet.png",
              "runs/<refs-run>/images/<char2>-sheet.png",
              "runs/<refs-run>/images/env-storyboard.png",
              "runs/<moodboard-run>/images/moodboard.png"
            ]
          }
        }
      }
    }]
  }],
  "output": { "format": "mp4" }
}
```

### Phase 5: Videos
Generate 15-second Seedance clips from the storyboard images.

```bash
python pipeline.py --resume-dir runs/<run-dir> --stage videos
```

### Phase 6: Final Assembly
```bash
python pipeline.py --resume-dir runs/<run-dir> --stage final
```

## Reference Chain

```
Moodboard collage (1 image — style anchor)
  ├── Character sheet per character (1 image each, moodboard as ref)
  ├── Environment storyboard (1 image, moodboard as ref)
  │
  └── Scene storyboard per clip (1 image each, ALL above as refs)
        └── 15-second Seedance video (storyboard as first_frame)
```

## Constants
- **Video model**: always `seedance-2.0`
- **Video duration**: always `15` seconds per clip
- **Image model**: always `nano-banana-pro`
- **Aspect ratio**: always `16:9` (landscape)
- **Every reference is a single collage/sheet image** — never multiple separate files
