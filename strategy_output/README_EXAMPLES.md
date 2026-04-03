# Timeline Format — Examples Guide

Practical examples showing what you can build with timeline JSON files. Each section is a standalone pattern you can copy and adapt.

---

## Table of Contents

- [Minimal Video](#minimal-video)
- [Narrated Explainer](#narrated-explainer)
- [Chained Sequence](#chained-sequence)
- [Two-Phase Character References](#two-phase-character-references)
- [Timestamp-Directed Long Takes](#timestamp-directed-long-takes)
- [Exploration / Style Testing](#exploration--style-testing)
- [Pre-Recorded Voice Over](#pre-recorded-voice-over)
- [Multi-Track Audio Mixing](#multi-track-audio-mixing)
- [Title Card + Video](#title-card--video)
- [Portrait / Vertical Video (9:16)](#portrait--vertical-video-916)
- [Model Comparison](#model-comparison)
- [Reference](#reference)

---

## Minimal Video

The simplest possible timeline — one video clip, no narration, no frills.

```json
{
  "version": 1,
  "project": { "name": "Single Clip" },
  "tracks": [
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-1",
          "source": {
            "type": "video",
            "prompt": "A cat sitting on a windowsill watching rain, cozy interior, soft lighting",
            "model": "veo-3.1-lite",
            "duration": 6
          }
        }
      ]
    }
  ]
}
```

**What happens:** Generates a single 6-second video. No image generation, no audio mixing.

---

## Minimal Video with Generated First Frame

Control the starting visual by generating an image first, then animating from it.

```json
{
  "version": 1,
  "project": { "name": "Controlled Start" },
  "tracks": [
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-1",
          "source": {
            "type": "video",
            "prompt": "The cat stretches and yawns, rain streaks down the window behind it",
            "model": "veo-3.1-lite",
            "duration": 6,
            "first_frame": {
              "generate": {
                "type": "image",
                "prompt": "A fluffy orange tabby cat curled up on a windowsill, rain on the glass, warm interior lighting, photorealistic"
              }
            }
          }
        }
      ]
    }
  ]
}
```

**What happens:** Generates the image first, then uses it as frame 1 of the video. The video animates *from* that exact image.

---

## Narrated Explainer

The core use case — narration synced to visuals. Each video clip's duration automatically matches its narration.

```json
{
  "version": 1,
  "project": {
    "name": "How Photosynthesis Works",
    "description": "3-clip narrated explainer"
  },
  "defaults": {
    "video": {
      "model": "veo-3.1-fast",
      "duration": 6,
      "generate_audio": false
    },
    "tts": {
      "voice": "Kore",
      "voice_prompt": "Calm, clear educational narrator"
    }
  },
  "tracks": [
    {
      "id": "narration",
      "type": "narration",
      "clips": [
        {
          "id": "narr-1",
          "source": {
            "type": "tts",
            "text": "Photosynthesis begins when sunlight hits the surface of a leaf."
          }
        },
        {
          "id": "narr-2",
          "source": {
            "type": "tts",
            "text": "Inside the chloroplasts, light energy splits water molecules into hydrogen and oxygen."
          }
        },
        {
          "id": "narr-3",
          "source": {
            "type": "tts",
            "text": "The hydrogen combines with carbon dioxide to create glucose — the plant's food."
          }
        }
      ]
    },
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-1",
          "fit_to": "narr-1",
          "source": {
            "type": "video",
            "prompt": "Sunlight beams hitting a vibrant green leaf, macro shot, light particles visible",
            "first_frame": {
              "generate": {
                "type": "image",
                "prompt": "Macro photograph of a green leaf with sunlight streaming through it, visible cell structure, vibrant green"
              }
            }
          }
        },
        {
          "id": "vid-2",
          "fit_to": "narr-2",
          "source": {
            "type": "video",
            "prompt": "Microscopic view inside a chloroplast, water molecules splitting apart, blue and green colors"
          }
        },
        {
          "id": "vid-3",
          "fit_to": "narr-3",
          "source": {
            "type": "video",
            "prompt": "Molecular animation of glucose forming from hydrogen and CO2, warm golden glow"
          }
        }
      ]
    }
  ],
  "output": {
    "variants": {
      "narration_only": true
    }
  }
}
```

**Key pattern:** `"fit_to": "narr-1"` makes the video duration match the TTS audio duration. The pipeline generates narration first (to know the duration), then generates videos to fit.

---

## Chained Sequence

Visual continuity — each clip starts where the previous one ended.

```json
{
  "version": 1,
  "project": { "name": "Sunrise to Storm" },
  "defaults": {
    "video": {
      "model": "veo-3.1-lite",
      "duration": 6,
      "generate_audio": true
    }
  },
  "tracks": [
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-dawn",
          "source": {
            "type": "video",
            "prompt": "Calm ocean at golden hour, gentle waves lapping a rocky shore, warm light on water",
            "first_frame": {
              "generate": {
                "type": "image",
                "prompt": "Calm turquoise ocean at golden hour, gentle waves, rocky coastline, warm sunlight"
              }
            }
          }
        },
        {
          "id": "vid-clouds",
          "source": {
            "type": "video",
            "prompt": "Clouds gathering over the ocean, light dimming, waves growing choppier",
            "first_frame": {
              "ref": "vid-dawn",
              "extract": "last_frame"
            }
          }
        },
        {
          "id": "vid-storm",
          "source": {
            "type": "video",
            "prompt": "Violent ocean storm, dark clouds, massive waves crashing against rocks, lightning",
            "first_frame": {
              "ref": "vid-clouds",
              "extract": "last_frame"
            }
          }
        }
      ]
    }
  ]
}
```

**Key pattern:** `"ref": "vid-dawn", "extract": "last_frame"` takes the final frame of the previous clip and uses it as the starting frame of the next. Creates a continuous visual flow.

**Trade-off:** Clips must generate sequentially (each depends on the previous), so no parallelism. For 3+ clips, this is noticeably slower than independent clips.

---

## Two-Phase Character References

Phase 1: generate character/scene reference sheets. Phase 2: use them to guide consistent video.

### Phase 1 — Generate References

```json
{
  "_comment": "Run with: --stage images",
  "version": 1,
  "project": { "name": "Character Refs" },
  "defaults": {
    "image": {
      "aspect_ratio": "9:16",
      "resolution": "2K"
    }
  },
  "tracks": [
    {
      "id": "refs",
      "type": "video",
      "clips": [
        {
          "id": "hero-ref",
          "source": {
            "type": "image",
            "prompt": "Anime character portrait, a young warrior with long black hair and a scar across his left cheek, wearing red and gold armor, determined expression, clean background",
            "reference_images": ["source_frames/hero_screenshot.jpg"]
          }
        },
        {
          "id": "villain-ref",
          "source": {
            "type": "image",
            "prompt": "Anime character portrait, a tall pale sorcerer in dark robes with silver hair, cold calculating eyes, clean background",
            "reference_images": ["source_frames/villain_screenshot.jpg"]
          }
        },
        {
          "id": "castle-ref",
          "source": {
            "type": "image",
            "prompt": "Anime environment, a dark gothic castle on a cliff at twilight, purple sky, bats circling the towers"
          }
        }
      ]
    }
  ],
  "output": {
    "variants": { "images_only": true }
  }
}
```

### Phase 2 — Video Using References

```json
{
  "version": 1,
  "project": { "name": "Battle Scene" },
  "defaults": {
    "video": { "model": "veo-3.1-lite", "duration": 8, "aspect_ratio": "9:16" },
    "image": { "aspect_ratio": "9:16" }
  },
  "tracks": [
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-approach",
          "source": {
            "type": "video",
            "prompt": "Anime scene, a young warrior in red armor approaches a dark castle on a cliff, wind blowing his hair, determined stride",
            "first_frame": {
              "generate": {
                "type": "image",
                "prompt": "Anime scene, warrior in red and gold armor with scar on cheek, standing before a gothic castle at twilight",
                "reference_images": [
                  "refs/characters/hero.png",
                  "refs/scenes/castle.png"
                ]
              }
            }
          }
        },
        {
          "id": "vid-confrontation",
          "source": {
            "type": "video",
            "prompt": "Anime scene, the warrior draws his sword as a pale sorcerer in dark robes emerges from the castle gates, dramatic wind",
            "first_frame": {
              "generate": {
                "type": "image",
                "prompt": "Anime scene, warrior in red armor facing a tall pale sorcerer in dark robes at a castle gate, dramatic lighting",
                "reference_images": [
                  "refs/characters/hero.png",
                  "refs/characters/villain.png",
                  "refs/scenes/castle.png"
                ]
              }
            }
          }
        }
      ]
    }
  ]
}
```

**Key pattern:** `reference_images` on the image source guides the generation toward specific character designs and environments. The generated images are "style-locked" by the references, then used as video first frames.

**Why two phases:** You generate and review character sheets first (cheap, fast, iterate on the look). Once the designs are locked in, the video generation is guided by consistent references — avoiding character drift across clips.

---

## Timestamp-Directed Long Takes

Instead of many short clips, use timestamp annotations inside the prompt to choreograph a single long clip.

```json
{
  "version": 1,
  "project": { "name": "Courtroom Drama" },
  "defaults": {
    "video": { "model": "veo-3.1-lite", "duration": 8, "aspect_ratio": "9:16" }
  },
  "tracks": [
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-1",
          "source": {
            "type": "video",
            "prompt": "Anime scene in a candlelit throne room, portrait framing, detailed cel-shading. [0:00] A stern king sits on his throne, staring ahead with contempt. [0:02] An advisor rushes in from the left, bowing deeply. [0:04] The king leans forward, slamming his fist on the armrest. [0:06] Close-up of the king's furious eyes, candlelight flickering.",
            "first_frame": {
              "generate": {
                "type": "image",
                "prompt": "Anime, a stern king on a throne in a candlelit chamber, dark robes, intense stare, portrait orientation"
              }
            }
          }
        }
      ]
    }
  ]
}
```

**Key pattern:** `[0:00]`, `[0:02]`, etc. inside the prompt tell the video model when each beat should happen. Fewer clips means fewer seams, and the model handles internal pacing.

**When to use:** Long dialogue scenes, continuous action, or when visual continuity matters more than precise scene matching.

---

## Exploration / Style Testing

Generate multiple visual directions, review them, then commit to the best one.

### Step 1 — Define candidates (run to generate all)

```json
{
  "version": 1,
  "project": { "name": "Style Exploration" },
  "assets": {
    "hero-image": {
      "type": "image",
      "prompt": "A futuristic city skyline at dusk",
      "candidates": [
        { "prompt": "Photorealistic futuristic city skyline at dusk, neon lights, rain-slicked streets" },
        { "prompt": "Cyberpunk illustrated city skyline at dusk, bold colors, stylized geometry" },
        { "prompt": "Studio Ghibli style futuristic city at dusk, soft lighting, whimsical architecture" }
      ]
    }
  },
  "tracks": [
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-1",
          "source": {
            "type": "video",
            "model": "veo-3.1-lite",
            "duration": 6,
            "prompt": "Camera slowly pushes through the futuristic cityscape at dusk, neon reflections",
            "first_frame": { "ref": "hero-image" }
          }
        }
      ]
    }
  ]
}
```

### Step 2 — Review outputs, then add `select`

```json
{
  "assets": {
    "hero-image": {
      "type": "image",
      "prompt": "A futuristic city skyline at dusk",
      "candidates": [
        { "prompt": "Photorealistic futuristic city..." },
        { "prompt": "Cyberpunk illustrated city..." },
        { "prompt": "Studio Ghibli style..." }
      ],
      "select": 2
    }
  }
}
```

**Key pattern:** `candidates` generates all variants. `select: 2` (1-based) locks in candidate 2. On the next run, only the selected candidate is generated.

**Works on:** image, video, and tts sources. Candidates override fields from the parent — only include fields that differ.

---

## Pre-Recorded Voice Over

Use an existing audio file instead of TTS. Extract segments with `start`/`end`.

```json
{
  "version": 1,
  "project": { "name": "Product Walkthrough" },
  "defaults": {
    "video": { "model": "veo-3.1-fast", "generate_audio": false }
  },
  "tracks": [
    {
      "id": "narration",
      "type": "narration",
      "clips": [
        {
          "id": "narr-intro",
          "source": {
            "type": "file",
            "path": "recordings/walkthrough.mp3",
            "start": 0,
            "end": 12.5
          }
        },
        {
          "id": "narr-features",
          "source": {
            "type": "file",
            "path": "recordings/walkthrough.mp3",
            "start": 12.5,
            "end": 28.0
          }
        },
        {
          "id": "narr-closing",
          "source": {
            "type": "file",
            "path": "recordings/outro.mp3"
          }
        }
      ]
    },
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-intro",
          "fit_to": "narr-intro",
          "source": {
            "type": "video",
            "prompt": "Sleek product floating in space, soft studio lighting, slow rotation"
          }
        },
        {
          "id": "vid-features",
          "fit_to": "narr-features",
          "source": {
            "type": "video",
            "prompt": "Product exploded view showing internal components, technical diagram style"
          }
        },
        {
          "id": "vid-closing",
          "fit_to": "narr-closing",
          "source": {
            "type": "video",
            "prompt": "Product on a desk in a modern office, pull back to wide shot, warm lighting"
          }
        }
      ]
    }
  ],
  "output": {
    "variants": { "narration_only": true }
  }
}
```

**Key pattern:** `file` sources with `start`/`end` let you slice a long recording into segments. Each video uses `fit_to` to match the audio segment's duration. File paths are relative to the timeline JSON file.

---

## Multi-Track Audio Mixing

Layer narration, background music, and sound effects on separate tracks with independent volume control.

```json
{
  "version": 1,
  "project": { "name": "Cooking Tutorial" },
  "defaults": {
    "video": { "model": "veo-3.1-fast", "generate_audio": true },
    "tts": {
      "voice": "Aoede",
      "voice_prompt": "Warm, friendly cooking show host"
    }
  },
  "tracks": [
    {
      "id": "narration",
      "type": "narration",
      "clips": [
        {
          "id": "narr-prep",
          "source": { "type": "tts", "text": "Start by dicing the onions into quarter-inch cubes." }
        },
        {
          "id": "narr-cook",
          "source": { "type": "tts", "text": "Heat olive oil in a cast iron skillet until it just begins to shimmer." }
        },
        {
          "id": "narr-plate",
          "source": { "type": "tts", "text": "Plate with a sprig of fresh rosemary and serve immediately." }
        }
      ]
    },
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-prep",
          "fit_to": "narr-prep",
          "source": {
            "type": "video",
            "prompt": "Hands dicing onions on a wooden cutting board, kitchen, overhead shot"
          }
        },
        {
          "id": "vid-cook",
          "fit_to": "narr-cook",
          "source": {
            "type": "video",
            "prompt": "Olive oil heating in a cast iron skillet, kitchen, close-up shot"
          }
        },
        {
          "id": "vid-plate",
          "fit_to": "narr-plate",
          "source": {
            "type": "video",
            "prompt": "Plating food on a white dish with rosemary garnish, warm kitchen light"
          }
        }
      ]
    },
    {
      "id": "music",
      "type": "audio",
      "volume": 0.15,
      "clips": [
        {
          "id": "bgm",
          "source": {
            "type": "file",
            "path": "music/light-acoustic.mp3"
          }
        }
      ]
    },
    {
      "id": "sfx",
      "type": "audio",
      "volume": 0.3,
      "clips": [
        {
          "id": "sfx-chop",
          "source": { "type": "file", "path": "sfx/chopping.wav" }
        },
        {
          "id": "sfx-gap",
          "source": { "type": "silence", "duration": 2.0 }
        },
        {
          "id": "sfx-sizzle",
          "source": { "type": "file", "path": "sfx/sizzle.wav" }
        }
      ]
    }
  ],
  "output": {
    "narration_volume": 1.0,
    "sfx_volume": 0.3,
    "audio_mix": {
      "narration": 1.0,
      "music": 0.15,
      "sfx": 0.3
    },
    "variants": {
      "narration_only": true,
      "narration_sfx": true
    }
  }
}
```

**Key patterns:**
- `"type": "audio"` tracks carry music and SFX alongside the narration track
- `volume` on a track sets its default level
- `silence` sources insert gaps between SFX clips
- `audio_mix` in output gives per-track volume override
- `generate_audio: true` on videos captures ambient sound (sizzle, chopping) from the video model
- Two output variants: one narration-only, one with everything mixed

---

## Title Card + Video

Use `still` sources to hold a static image as a title card before the video starts.

```json
{
  "version": 1,
  "project": { "name": "Title Card Demo" },
  "assets": {
    "title-image": {
      "type": "image",
      "prompt": "Elegant title card on dark background, text reads 'Chapter One', gold serif font, cinematic"
    }
  },
  "tracks": [
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "title-card",
          "source": {
            "type": "still",
            "image": { "ref": "title-image" },
            "duration": 3.0
          }
        },
        {
          "id": "vid-opening",
          "source": {
            "type": "video",
            "model": "veo-3.1-lite",
            "duration": 8,
            "prompt": "Camera slowly pushing through a dark forest, morning mist, cinematic"
          }
        }
      ]
    }
  ]
}
```

**Key pattern:** `still` source holds a generated (or referenced) image for a fixed duration. The asset `title-image` is generated once and referenced by the still clip.

---

## Portrait / Vertical Video (9:16)

Set aspect ratio globally for short-form vertical content.

```json
{
  "version": 1,
  "project": {
    "name": "Vertical Short",
    "aspect_ratio": "9:16",
    "resolution": "720p"
  },
  "defaults": {
    "video": {
      "model": "veo-3.1-lite",
      "aspect_ratio": "9:16",
      "generate_audio": true
    },
    "image": {
      "aspect_ratio": "9:16"
    }
  },
  "tracks": [
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-1",
          "source": {
            "type": "video",
            "duration": 8,
            "prompt": "Vertical phone video style, a person walking through a neon-lit alley in Tokyo at night, handheld camera feel"
          }
        }
      ]
    }
  ]
}
```

**Note:** Set `aspect_ratio: "9:16"` on both video and image defaults. The project-level `aspect_ratio` is metadata — the source-level fields are what the models actually use.

---

## Model Comparison

Same scene across different video models to compare quality and style.

```json
{
  "version": 1,
  "project": { "name": "Model Comparison" },
  "assets": {
    "shared-frame": {
      "type": "image",
      "prompt": "A knight standing at the edge of a cliff overlooking a vast fantasy landscape, sunrise, cinematic wide shot"
    }
  },
  "tracks": [
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-lite",
          "source": {
            "type": "video",
            "model": "veo-3.1-lite",
            "duration": 6,
            "prompt": "The knight draws his sword and raises it to the sky, wind blowing his cape, sunrise",
            "first_frame": { "ref": "shared-frame" }
          }
        },
        {
          "id": "vid-fast",
          "source": {
            "type": "video",
            "model": "veo-3.1-fast",
            "duration": 6,
            "prompt": "The knight draws his sword and raises it to the sky, wind blowing his cape, sunrise",
            "first_frame": { "ref": "shared-frame" }
          }
        },
        {
          "id": "vid-quality",
          "source": {
            "type": "video",
            "model": "veo-3.1",
            "duration": 6,
            "prompt": "The knight draws his sword and raises it to the sky, wind blowing his cape, sunrise",
            "first_frame": { "ref": "shared-frame" }
          }
        },
        {
          "id": "vid-kling",
          "source": {
            "type": "video",
            "model": "kling-v3",
            "prompt": "The knight draws his sword and raises it to the sky, wind blowing his cape, sunrise",
            "first_frame": { "ref": "shared-frame" }
          }
        }
      ]
    }
  ]
}
```

**Key pattern:** A shared `asset` generates the first frame once. All 4 video clips reference the same image but use different models. All 4 videos generate concurrently since they share no dependencies beyond the asset.

---

## Reference

### Available Models

| Model | Type | Durations | Resolutions | Notes |
|-------|------|-----------|-------------|-------|
| `veo-3.1` | Video | 4, 6, 8s | 720p, 1080p | Highest quality |
| `veo-3.1-fast` | Video | 4, 6, 8s | 720p | Default, good for iteration |
| `veo-3.1-lite` | Video | 4, 6, 8s | 720p, 1080p | Cheapest, audio always on |
| `kling-v3` | Video | model-determined | 720p, 1080p | Alternative aesthetic |
| `nano-banana-pro` | Image | — | up to 2K | Default image model |
| `gemini-2.5-flash-tts` | TTS | — | — | 29 voices, style prompts |

### Source Types

| Type | Use for | Key fields |
|------|---------|------------|
| `video` | Generate video clips | `prompt`, `first_frame`, `last_frame`, `model`, `duration`, `generate_audio`, `negative_prompt`, `seed` |
| `image` | Generate images | `prompt`, `reference_images`, `candidates`, `select` |
| `tts` | Generate speech | `text`, `voice`, `voice_prompt`, `candidates`, `select` |
| `file` | Existing audio/video | `path`, `start`, `end` |
| `silence` | Insert gaps | `duration` |
| `still` | Static image as video | `image` (path, URL, or ref), `duration` |

### Key Timing Patterns

| Pattern | What it does |
|---------|-------------|
| `"fit_to": "narr-1"` | Video duration matches narration clip |
| `"duration": 6` | Fixed duration (clip level overrides source) |
| `"duration": "auto"` | Source determines duration (default) |
| `"buffer_ms": 500` | 500ms gap before this clip |
| `"fit_method": "speed"` | Adjust playback speed to match target |

### Key Reference Patterns

| Pattern | What it does |
|---------|-------------|
| `{ "ref": "asset-id" }` | Use full output of an asset or clip |
| `{ "ref": "vid-1", "extract": "last_frame" }` | Extract last frame from a video |
| `{ "ref": "vid-1", "extract": "first_frame" }` | Extract first frame from a video |
| `{ "generate": { "type": "image", ... } }` | Generate inline (one-off first frame) |
| `"reference_images": ["path.jpg"]` | Style-guide image generation from existing images |

### TTS Voices (Gemini)

**Female:** Achernar, Aoede, Autonoe, Callirrhoe, Despina, Erinome, Gacrux, Kore, Laomedeia, Leda, Pulcherrima, Sulafat, Vindemiatrix, Zephyr

**Male:** Achird, Algenib, Algieba, Alnilam, Charon, Enceladus, Fenrir, Iapetus, Orus, Puck, Rasalgethi, Sadachbia, Sadaltager, Schedar, Umbriel

Use `voice_prompt` to control tone: `"Warm and enthusiastic"`, `"Serious documentary narrator"`, `"Whispered, intimate"`, etc.
