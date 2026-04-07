# Strategy E: Studio Workflow (UI-Driven)

## Approach
Multi-phase pipeline driven by the MoGraph Studio UI. Each phase maps to a step in the UI. The key difference from Strategy D is that **moodboard images are the style anchor** — they replace extracted video frames as the initial reference source. Characters and environments are generated from moodboard + descriptions, then every scene image uses the full reference chain.

## Why this strategy
- **No source footage required**: Strategy D depends on extracted frames for initial references. Strategy E starts from scratch — a text description or curated moodboard folder sets the visual direction.
- **Reference chain ensures consistency**: Moodboard → character/environment refs → scene first-frames → videos. Each phase inherits references from the one before.
- **UI-friendly**: Each phase is a discrete step with review/iteration before committing to the next. The studio UI provides edit/regenerate controls at every stage.
- **Works with any project**: Not locked to a specific scene or character set.

## Phases

### Phase 1: Moodboard (`moodboard-timeline.json`)
Generate 4-6 reference images that establish the visual style: color palette, art style, lighting mood, composition language.

**Input**: A style description (e.g. "Dark fantasy anime, candlelit medieval interiors, warm amber palette, cel-shaded").
**Output**: `runs/<name>_Moodboard-<timestamp>/images/mood-*.png`

These moodboard images become `reference_images` for ALL subsequent generation.

```bash
python pipeline.py --timeline-file moodboard-timeline.json --stage images
```

### Phase 2: Character & Environment Refs (`refs-timeline.json`)
Generate dedicated reference sheets for each character and the environment. **Every ref clip uses moodboard images as reference_images** to lock in the style.

**Input**: Character names + visual descriptions, environment description, moodboard image paths.
**Output**: `runs/<name>_Refs-<timestamp>/images/<character-name>-ref.png`, `env-ref.png`

```bash
python pipeline.py --timeline-file refs-timeline.json --stage images
```

After review, copy the best refs to a `refs/` folder for Phase 4.

### Phase 3: Story Arc (no pipeline — planning only)
Define the scenes. This is a creative step — the UI asks Claude to break a story prompt into 3-6 scenes, each with:
- `label` — Scene title
- `prompt` — Video prompt (describes motion/action)
- `firstFramePrompt` — Still image prompt for the first frame

No pipeline runs in this phase. Output is a scenes JSON structure.

### Phase 4: Images (`timeline.json --stage images`)
Write the full timeline and generate first-frame images. **Every scene's `first_frame.generate.reference_images` includes the character refs + environment ref + moodboard images.** This is the critical consistency mechanism.

```bash
python pipeline.py --timeline-file timeline.json --stage images
```

Review images. Edit prompts and regenerate individual clips as needed. The reference images ensure characters look the same across all scenes.

### Phase 5: Videos (`--resume-dir <run> --stage videos`)
Generate video clips from approved first-frame images.

```bash
python pipeline.py --resume-dir runs/<run-dir> --stage videos
```

### Phase 6: Final Assembly (`--resume-dir <run> --stage final`)
Concatenate all clips, overlay narration (if any), mix audio.

```bash
python pipeline.py --resume-dir runs/<run-dir> --stage final
```

## Reference chain diagram

```
Moodboard images (style anchor)
  ├── Character ref generation (moodboard as reference_images)
  │     ├── king-ref.png
  │     ├── advisor-ref.png
  │     └── ...
  ├── Environment ref generation (moodboard as reference_images)
  │     └── env-ref.png
  │
  └── Scene first-frame generation (ALL of the above as reference_images)
        ├── scene-1 first_frame: reference_images = [king-ref, advisor-ref, env-ref, mood-1, mood-2]
        ├── scene-2 first_frame: reference_images = [king-ref, env-ref, mood-1, mood-2]
        └── scene-3 first_frame: reference_images = [king-ref, advisor-ref, env-ref, mood-1, mood-2]
```

**The rule**: Every `reference_images` array should include:
1. The relevant character ref(s) for that scene
2. The environment ref
3. 1-2 moodboard images (for global style consistency)

## Timeline templates

### moodboard-timeline.json
```json
{
  "version": 1,
  "project": { "name": "<ProjectName>_Moodboard" },
  "defaults": {
    "image": { "model": "nano-banana-pro", "aspect_ratio": "9:16", "output_format": "png" }
  },
  "tracks": [{
    "id": "moodboard",
    "type": "video",
    "clips": [
      {
        "id": "mood-1",
        "label": "Style reference — establishing shot",
        "source": {
          "type": "image",
          "prompt": "<style prefix>, wide establishing shot of <environment>, <lighting>, <color palette>, portrait orientation"
        }
      },
      {
        "id": "mood-2",
        "label": "Style reference — character close-up",
        "source": {
          "type": "image",
          "prompt": "<style prefix>, medium close-up character portrait, <key visual traits>, <lighting>, portrait orientation"
        }
      }
    ]
  }]
}
```

### refs-timeline.json
```json
{
  "version": 1,
  "project": { "name": "<ProjectName>_Refs" },
  "defaults": {
    "image": { "model": "nano-banana-pro", "aspect_ratio": "9:16", "output_format": "png" }
  },
  "tracks": [{
    "id": "refs",
    "type": "video",
    "clips": [
      {
        "id": "<character-name>-ref",
        "label": "<Character> character portrait",
        "source": {
          "type": "image",
          "prompt": "<style prefix>, character portrait of <detailed description>, medium close-up, portrait orientation, clean background for character reference",
          "reference_images": [
            "runs/<moodboard-run>/images/mood-1.png",
            "runs/<moodboard-run>/images/mood-2.png"
          ]
        }
      },
      {
        "id": "env-ref",
        "label": "Environment establishing shot",
        "source": {
          "type": "image",
          "prompt": "<style prefix>, wide establishing shot of <environment description>, no characters, atmospheric, portrait orientation",
          "reference_images": [
            "runs/<moodboard-run>/images/mood-1.png"
          ]
        }
      }
    ]
  }]
}
```

### timeline.json (the main scene timeline)
```json
{
  "version": 1,
  "project": { "name": "<ProjectName>" },
  "defaults": {
    "video": { "model": "kling-v3", "generate_audio": false, "aspect_ratio": "9:16" },
    "image": { "model": "nano-banana-pro", "aspect_ratio": "9:16" }
  },
  "tracks": [{
    "id": "visuals",
    "type": "video",
    "clips": [
      {
        "id": "scene-1",
        "label": "<Scene title>",
        "source": {
          "type": "video",
          "prompt": "<video prompt with action/motion>",
          "first_frame": {
            "generate": {
              "type": "image",
              "prompt": "<still image prompt for first frame>",
              "reference_images": [
                "refs/characters/<char1>.png",
                "refs/characters/<char2>.png",
                "refs/scenes/env.png",
                "refs/moodboard/mood-1.png",
                "refs/moodboard/mood-2.png"
              ]
            }
          }
        }
      }
    ]
  }],
  "output": { "format": "mp4" }
}
```

## Key differences from Strategy D

| Aspect | Strategy D | Strategy E (Studio) |
|--------|-----------|---------------------|
| **Style source** | Extracted video frames | Moodboard images (generated or curated) |
| **Workflow** | Manual 2-phase CLI | 6-step UI with review at each stage |
| **Reference threading** | Refs → scene images | Moodboard → refs → scene images (deeper chain) |
| **Project specificity** | Hardcoded to throne room | Generic — any project, any characters |
| **Candidates** | 3 style variants per character | Optional (can regenerate from UI) |
| **Iteration** | Re-run CLI manually | Edit prompt + regenerate button per scene |

## Folder structure
```
strategies/e-studio-workflow/
  strategy.md                # This file
  refs/
    moodboard/               # Moodboard images (from Phase 1)
    characters/              # Character reference sheets (from Phase 2)
    scenes/                  # Environment refs (from Phase 2)
```

## How the Studio UI uses this

The MoGraph Studio (`/studio.html`) sends explicit task instructions to Claude via the bridge. Claude reads this strategy document for the workflow pattern, then:

1. **Moodboard step** → Writes `moodboard-timeline.json` per the template, runs `pipeline.py --stage images`
2. **Characters step** → Writes `refs-timeline.json` with moodboard images as `reference_images`, runs `pipeline.py --stage images`  
3. **Arc step** → Claude generates scenes JSON (no pipeline run)
4. **Images step** → Writes `timeline.json` with ALL refs (characters + env + moodboard) in every scene's `first_frame.generate.reference_images`, runs `pipeline.py --stage images`
5. **Videos step** → `pipeline.py --resume-dir <run> --stage videos`
6. **Finish step** → `pipeline.py --resume-dir <run> --stage final`

**Critical**: Claude MUST read `strategies/e-studio-workflow/strategy.md` before executing any step to understand the reference chain pattern.
