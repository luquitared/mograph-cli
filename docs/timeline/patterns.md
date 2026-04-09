# Timeline Patterns

Advanced workflow recipes and techniques for the timeline format.

---

## Cross-Referencing: Image to Video to Chain

The most common pattern: generate an image asset, use it as a video's first frame, then chain subsequent videos from the last frame.

```json
{
  "assets": {
    "hero": {
      "type": "image",
      "prompt": "A futuristic cityscape at dusk, neon lights reflecting on wet streets"
    }
  },
  "tracks": [{
    "id": "visuals",
    "type": "video",
    "clips": [
      {
        "id": "vid-1",
        "source": {
          "type": "video",
          "prompt": "Camera slowly pushes into the neon cityscape...",
          "first_frame": { "ref": "hero" }
        }
      },
      {
        "id": "vid-2",
        "source": {
          "type": "video",
          "prompt": "Camera continues through rain-soaked streets...",
          "first_frame": { "ref": "vid-1", "extract": "last_frame" }
        }
      }
    ]
  }]
}
```

**Key points:**
- `{ "ref": "hero" }` without `extract` uses the full image output
- `{ "ref": "vid-1", "extract": "last_frame" }` extracts the last frame from a video
- The executor resolves these dependencies automatically via DAG ordering
- Chains longer than 10 clips emit a warning (quality may degrade)

## Inline Generation with `generate`

Instead of defining a separate asset, generate a first frame inline:

```json
{
  "first_frame": {
    "generate": {
      "type": "image",
      "prompt": "Starting frame: dark room with a single spotlight"
    }
  }
}
```

Use named assets when the same image is referenced by multiple clips. Use `generate` for one-off first frames.

---

## Image-to-Image Chaining with Reference Images

Use `{"ref": "clip_id"}` in `reference_images` to feed one image generation's output as a reference into the next. This is useful for maintaining visual consistency across a sequence of images (e.g., character sheets, style references).

```json
{
  "tracks": [{
    "id": "visuals",
    "type": "video",
    "clips": [
      {
        "id": "character_sheet",
        "source": {
          "type": "image",
          "model": "nano-banana-2",
          "prompt": "Character reference sheet: warrior in silver armor, multiple angles"
        }
      },
      {
        "id": "scene_1",
        "source": {
          "type": "image",
          "model": "nano-banana-2",
          "prompt": "Warrior standing on a cliff at sunset, dramatic lighting",
          "reference_images": [{ "ref": "character_sheet" }]
        }
      },
      {
        "id": "scene_2",
        "source": {
          "type": "image",
          "model": "nano-banana-2",
          "prompt": "Warrior entering a dark cave, torch in hand",
          "reference_images": [{ "ref": "character_sheet" }, { "ref": "scene_1" }]
        }
      }
    ]
  }]
}
```

**Key points:**
- Refs and static file paths can be mixed: `"reference_images": ["assets/style.png", {"ref": "character_sheet"}]`
- The DAG ensures referenced clips generate before dependents
- Works with both `nano-banana-pro` and `nano-banana-2` models
- `extract` is supported: `{"ref": "vid-1", "extract": "first_frame"}` to use a frame from a video

---

## Exploration Workflow

Use `candidates` arrays to explore prompt variations, then `select` the winner.

### Step 1: Define candidates

```json
{
  "assets": {
    "hero": {
      "type": "image",
      "prompt": "Default prompt (used if no candidate selected)",
      "candidates": [
        { "prompt": "Variant A: photorealistic cityscape" },
        { "prompt": "Variant B: illustrated, stylized cityscape" },
        { "prompt": "Variant C: dark noir aesthetic" }
      ]
    }
  }
}
```

### Step 2: Run to generate all candidates

The executor generates all candidate variants. Review the outputs in the run directory.

### Step 3: Select the winner

Add `"select": 2` to use candidate index 2 (1-based). On next run, only the selected candidate is generated.

```json
{
  "candidates": [...],
  "select": 2
}
```

**Works on:** `image`, `video`, and `tts` sources. Candidates override fields from the parent source — only include fields that differ.

---

## Timing Strategies

### fit_to: Match Video Duration to Narration

The most common timing pattern — make each video clip match its corresponding narration clip:

```json
{
  "id": "vid-1",
  "fit_to": "narr-1",
  "source": { "type": "video", "prompt": "..." }
}
```

The executor determines `narr-1`'s duration (after TTS generation) and adjusts `vid-1` to match.

### fit_to: Match Narration to Video

Works the other direction too — if you have a fixed-duration video and want narration to fit:

```json
{
  "id": "narr-1",
  "fit_to": "vid-1",
  "source": { "type": "tts", "text": "..." }
}
```

### fit_method

Currently supports `"speed"` (default), which adjusts playback speed to match the target duration.

### buffer_ms

Add padding between clips:

```json
{
  "id": "vid-2",
  "buffer_ms": 500,
  "source": { "type": "video", "prompt": "..." }
}
```

Adds 500ms of gap before this clip in the assembled output.

### Avoiding Timing Cycles

The validator rejects circular fit_to references:

```
clip-a: fit_to: "clip-b"
clip-b: fit_to: "clip-a"   // ERROR: timing cycle
```

---

## Multi-Clip Fitting

For longer narration segments, you can chain multiple video clips that collectively fill the narration duration. Each video clip uses `fit_to` to match a portion of the narration:

```json
{
  "tracks": [
    {
      "id": "narration",
      "type": "narration",
      "clips": [
        { "id": "narr-intro", "source": { "type": "tts", "text": "Long intro..." } }
      ]
    },
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "vid-1a",
          "fit_to": "narr-intro",
          "duration": 6,
          "source": { "type": "video", "prompt": "First half of the scene" }
        },
        {
          "id": "vid-1b",
          "fit_to": "narr-intro",
          "source": { "type": "video", "prompt": "Second half, continuing the scene" }
        }
      ]
    }
  ]
}
```

---

## SFX Mixing and Volume Controls

### Track-Level Volume

Set volume on audio tracks to control their level in the mix:

```json
{
  "id": "sfx",
  "type": "audio",
  "volume": 0.2,
  "clips": [...]
}
```

### Output-Level Volume

Control narration and SFX volumes globally:

```json
{
  "output": {
    "narration_volume": 1.0,
    "sfx_volume": 0.3
  }
}
```

### Per-Track Mix Overrides

Use `audio_mix` for fine-grained per-track control:

```json
{
  "output": {
    "audio_mix": {
      "narration": 1.0,
      "music": 0.15,
      "sfx": 0.3
    }
  }
}
```

### Output Variants

Control which output files are produced:

```json
{
  "output": {
    "variants": {
      "narration_only": true,
      "narration_sfx": true,
      "images_only": false
    }
  }
}
```

- `narration_only` — Video with narration audio only
- `narration_sfx` — Video with narration + SFX/ambient audio mixed
- `images_only` — Export generated images without assembling video

---

## Audio Track Layering

Combine multiple audio sources on separate tracks:

```json
{
  "tracks": [
    {
      "id": "narration",
      "type": "narration",
      "clips": [
        { "id": "narr-1", "source": { "type": "tts", "text": "..." } }
      ]
    },
    {
      "id": "music",
      "type": "audio",
      "volume": 0.15,
      "clips": [
        { "id": "bgm", "source": { "type": "file", "path": "music/background.mp3" } }
      ]
    },
    {
      "id": "sfx",
      "type": "audio",
      "volume": 0.3,
      "clips": [
        { "id": "sfx-whoosh", "source": { "type": "file", "path": "sfx/whoosh.wav" } },
        { "id": "sfx-pad", "source": { "type": "silence", "duration": 2.0 } },
        { "id": "sfx-ding", "source": { "type": "file", "path": "sfx/ding.wav" } }
      ]
    }
  ]
}
```

**Tips:**
- Use `silence` sources to insert gaps between SFX clips
- Keep background music on its own track with low volume (0.1–0.2)
- Video tracks with `generate_audio: true` contribute ambient sound — control via `sfx_volume`
- The `narration` track type is special: it drives timing when other clips use `fit_to`

---

## File Sources for Pre-Recorded Audio

Use `file` sources to bring in existing audio. Segment extraction with `start`/`end` lets you split a long recording:

```json
{
  "source": {
    "type": "file",
    "path": "recordings/interview.mp3",
    "start": 30.0,
    "end": 45.5
  }
}
```

File paths are relative to the timeline JSON file's directory. URLs are also supported.

---

## Still Images as Video Placeholders

Use `still` sources to hold a static image for a fixed duration — useful for title cards or placeholders:

```json
{
  "id": "title-card",
  "source": {
    "type": "still",
    "image": { "ref": "hero-image" },
    "duration": 3.0
  }
}
```

The `image` field accepts a path/URL string or a `ref` to an image-producing asset/clip.
