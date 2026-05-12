# News-Video Workflow

End-to-end recipe for generating a stylized animated news segment with a
recurring cast: anchor + co-host + a third "fact-source" character (e.g. a
robot). Uses Seedance for video, GPT Image 2 / Nano Banana for reference
images, and a small set of helper scripts for analysis and audio polish.

The pattern is generalizable. The example assets (`news-show-v1`) ship a
sakuga-style anime cast — sharp female anchor + himbo co-host + tin-robot
fact source — but the workflow is the same if you swap to claymation, 3D,
or any other style.

## Inputs

- `.env` with `REPLICATE_API_TOKEN` (Seedance + GPT Image 2 routing) and
  `GOOGLE_API_KEY` (Gemini analysis + Nano Banana 2)
- An asset pack — either pull `news-show-v1` from GCS, or generate your own
  (Section 1)
- A topic + script — see Section 4 for the script-design checklist

## Outputs

- `<segment>.json` — timeline file
- `runs/<Project>-<timestamp>/videos/*.mp4` — individual clips
- `runs/<Project>-<timestamp>/final/video_concat.mp4` — raw concat
- `runs/<Project>-<timestamp>/final/video_polished.mp4` — after audio polish

## Quick start (using the example pack)

```bash
# 1. Pull example assets
python scripts/asset_pack_pull.py news-show-v1
# → runs/asset-packs/news-show-v1/{characters,voices,environments,composites}/

# 2. Run an example timeline
python pipeline.py --timeline-file docs/workflows/news-video/examples/news-segment-full.json --stage final

# 3. Polish audio
python scripts/polish_audio.py runs/Kalshi_Top_5_v2-*

# 4. (Optional) Critique
python scripts/critique_full_video.py runs/Kalshi_Top_5_v2-*/final/video_polished.mp4
```

---

## 1. Asset prep

A "news-video pack" contains three layers of reference assets.

### 1a. Character sheets (one per cast member)

For each character, generate a single image showing 3 turnaround poses + 4
expression close-ups on a neutral grey backdrop. Pass these as
`reference_images` in every Seedance clip the character appears in — this
keeps faces, costumes, and proportions stable across clips.

Pattern: build a manifest and run `scripts/batch_image_gen.py`:

```json
{
  "requests": [
    {
      "id": "maya",
      "model": "gpt-image-2",
      "prompt": "Character sheet: 'Maya', the sharp competent news anchor co-host. Late 20s woman, ... Three full-body poses on a neutral grey backdrop (front, 3/4, side), plus a row of four expression close-ups beneath (warm smile, deadpan eyebrow-raise, laughing, surprised reaction). STYLE: high-effort sakuga-style hand-drawn Japanese animation, ...",
      "output_path": "runs/asset-packs/<your-pack>/characters/sakuga_maya.png",
      "aspect_ratio": "3:2",
      "output_format": "png",
      "quality": "high"
    },
    { "id": "trip", ... },
    { "id": "faq9000", ... }
  ],
  "concurrency": 5
}
```

```bash
python scripts/batch_image_gen.py character-sheets-manifest.json
```

### 1b. Environment / set ref (optional but useful)

Single image of the empty news studio. Acts as a "set bible" — keeps the
desk, monitor wall, and lighting consistent across on-set clips. Same
pattern, single request.

### 1c. B-roll scene refs (one per b-roll subject)

Each b-roll cutaway needs a scene ref so Seedance has something to anchor
its visuals to. **Critical**: b-roll uses `reference_audios` for VO
voice-matching, and Seedance requires `reference_images` whenever
`reference_audios` is set (see Section 9). Use a scene-only ref (no
characters) for these.

---

## 2. Voice references — the consistency unlock

Seedance's `reference_audios` field accepts a 5–15s WAV of the desired
voice. The model generates new dialogue in that voice. This is the single
biggest win for cast continuity across clips.

### 2a. First-clip extraction

Generate the first segment as text-to-video with no `reference_audios`:
Seedance picks voices for the cast. Then extract per-character WAVs from
that clip and reuse them in every subsequent clip.

```bash
# 1. Run the first clip (e.g. cold open with all 3 characters speaking)
python pipeline.py --timeline-file initial.json --stage videos

# 2. Get speaker timestamps via Gemini
python scripts/analyze_news_clip.py runs/.../videos/01-cold-open.mp4
# → JSON with [{name, start, end, line, voice_notes}, ...]

# 3. Extract each speaker's audio with ffmpeg
ffmpeg -i input.mp4 -ss 0.0 -to 5.8 -vn -c:a pcm_s16le maya_voice.wav
ffmpeg -i input.mp4 -ss 5.8 -to 9.8 -vn -c:a pcm_s16le trip_voice.wav

# 4. Reference them in subsequent clips
"reference_audios": [
  "runs/asset-packs/<pack>/voices/maya_voice.wav",
  "runs/asset-packs/<pack>/voices/trip_voice.wav"
]
```

### 2b. Constraints (Seedance)

- Max 3 audio refs per clip
- Combined max 15s
- **`reference_audios` REQUIRES at least one `reference_images` or
  `reference_videos`** — you cannot pass audio refs alone
- Robot/non-human voices: extract from your first clip the same way; the
  voice-clone holds for stylized voices too

---

## 3. Topic-introducing composite refs

For a multi-topic segment (e.g. top-5 list), each topic-introduction clip
benefits enormously from a **composite reference image** that already shows
the topic on screen. This solves two problems:

1. Establishes the topic visually before the dialogue starts (clear
   antecedent — the "who's `he`?" problem disappears)
2. Lets you put a recognizable topic figure on a TV monitor inside the set
   without asking Seedance to render it from scratch (which it does
   unreliably for text + faces)

### 3a. The composite pattern

Each composite is one image: cast at the desk + topic figure rendered as a
portrait on the central TV monitor + a bold caption with the topic name.
Generate via `gpt-image-2` (best at text rendering) and pass the existing
character sheets as `reference_images` so the cast looks right.

See `composites/comp_dhs.png` in the example pack for the canonical version.

### 3b. Wiring it into a clip

```json
{
  "id": "pick-dhs",
  "duration": 12,
  "source": {
    "type": "video",
    "prompt": "[0.0s-2.0s] HOLD on the establishing shot — the audience clearly sees the title card on the central monitor behind the cast. [2.0s-...] Maya turns to camera and delivers ...",
    "reference_images": [
      "runs/asset-packs/<pack>/composites/comp_dhs.png",
      "runs/asset-packs/<pack>/characters/sakuga_maya.png",
      "runs/asset-packs/<pack>/characters/sakuga_trip.png",
      "runs/asset-packs/<pack>/characters/sakuga_faq9000.png"
    ],
    "reference_audios": [
      "runs/asset-packs/<pack>/voices/maya_voice.wav",
      "runs/asset-packs/<pack>/voices/trip_voice.wav"
    ]
  }
}
```

The composite goes **first** in `reference_images` — Seedance weights ref[0]
most heavily for composition. Character sheets follow as fidelity refs.

### 3c. ⚠️ Likeness caveat

Seedance has a copyright filter that fires on **recognizable politician
likenesses** even when stylized as anime portraits — separate from the
photoreal-face E005 block. We hit this on a Trump composite. The DHS
composite (no portrait, just a Capitol illustration) and a Patel composite
(less internationally recognized face) both passed. Workarounds for
high-recognition figures:

- Use a silhouette / back-of-head / shadowed figure
- Use a symbolic image (Air Force One, the agency's seal, a flag) with the
  caption doing the load-bearing identification
- Caption-only on the TV monitor — no portrait at all

---

## 4. Script design

### 4a. Cast roles

Three roles with sharp tonal distinction make the comedy work:

- **Anchor** — straight-deliverer. Sets up the topic with real numbers.
- **Co-host** — comic foil. Lands the joke by undermining the anchor (or
  themselves). Best as confidently wrong rather than self-aware.
- **Fact source** — non-human (robot / AI / oracle). Delivers cold
  numerical truth. The more deadpan, the funnier.

The three-beat structure for each topic clip:

1. Anchor names the topic clearly (with a noun, not a pronoun — see
   pitfalls below)
2. Fact source delivers numbers
3. Co-host's reaction lands the joke

### 4b. Pacing — WPS 2.5

To size each clip, count your dialogue words and divide by 2.5
(words-per-second average for natural speech). Add a 1–2s buffer for pauses
and beats. Round UP to integer seconds (Seedance requires int 4–15).

Example: 23 words → 23/2.5 = 9.2s → use `"duration": 11` (gives ~1.8s
breathing room).

### 4c. Timestamps in prompts

Seedance honors timestamped beats inside a prompt. Structure each on-set
clip as:

```
[0.0s-2.0s] HOLD on establishing shot — title card visible on TV.
[2.0s-X.Xs] Anchor delivers: '<exact line>' in <voice description>.
[X.Xs-Y.Ys] Fact source intones: '<exact line>'.
[Y.Ys-end] Co-host reacts: '<exact line>'.
```

The `[0.0s-2.0s] HOLD` opening is the move that makes topic intros feel
intentional — gives the title card time to register before the dialogue
starts.

---

## 5. B-roll cutaways

Cutaways from the on-set picks to topic-relevant footage are essential for
news-show feel. Pattern:

- No characters in frame (`"NO CHARACTERS visible on camera"` early in
  prompt)
- Single subject per clip — Seedance over-stabilizes when you ask for two
  cuts in 8s
- **Lead with motion**: `"FULLY ANIMATED, CONTINUOUS MOTION THROUGHOUT —
  not a still image"`. Without this Seedance treats the scene ref as a
  locked still and only does light pans
- VO-only audio: `reference_audios` with one cast voice WAV + the scene
  ref as `reference_images`

Length: 6–10s. Insert after the on-set clip that introduces the topic.

---

## 6. Timeline structure

A typical multi-topic news segment:

```
1.  Cold open                  — full cast, no composite, intro hook
2.  Pick #N (topic A intro)    — composite-A ref, on-set
3.  B-roll for topic A         — scene-A ref, no characters, VO
4.  Pick #N-1 (topic B intro)  — composite-B ref, on-set
5.  B-roll for topic B         — scene-B ref, no characters, VO
6.  Pick #N-2 (callback to A)  — composite-A ref again (consistency)
...
N.  Outro                      — full cast, no composite
```

Total target: 60–120s. See
`docs/workflows/news-video/examples/news-segment-full.json` for a concrete 7-clip
example.

### Reference type cheat sheet

| Need | Use |
|---|---|
| Character look consistency | `reference_images: [character_sheets...]` |
| Voice continuity | `reference_audios: [voice_wavs...]` (REQUIRES image/video ref) |
| Set / topic visual lock | `reference_images: [composite_or_scene_ref, ...]` (put first) |
| Scene-to-scene continuation | `reference_videos: [{"ref": "prev-clip-id"}]` |
| Exact starting frame | `first_frame: {generate: {...}}` (mutually exclusive with `reference_images`) |

`reference_images` and `first_frame` are mutually exclusive on Seedance.
Since `reference_audios` requires image/video refs, voice continuity locks
you out of `first_frame`. Plan accordingly.

---

## 7. Audio polish

After the pipeline produces a concat, run:

```bash
python scripts/polish_audio.py runs/<Project>-<timestamp>
```

This loudnorms each individual clip to broadcast EBU R128 (-16 LUFS) and
re-concats. Fixes the "Trip is 6dB louder than Maya" problem you'll
otherwise hit. Output: `<run>/final/video_polished.mp4`.

---

## 8. Critique loop

Before iterating on prompts, get a structured critique:

```bash
# Per-clip critique against a brief
python scripts/critique_clip.py path/to/clip.mp4 "what this clip was supposed to do"

# Whole-video critique
python scripts/critique_full_video.py path/to/final.mp4
```

Both invoke `gemini-3.1-pro-preview` with structured JSON schemas covering
visuals / audio / dialogue transcription / character drift / joke landing /
suggested fixes. Use the `biggest_fixes[]` array as a punch list.

---

## 9. Common pitfalls (Seedance-specific)

| Symptom | Cause | Fix |
|---|---|---|
| `E005` content moderation on retry loop | Photoreal-human reference image | Stylized refs (claymation, anime, illustrated) pass. Don't use action-figure photography as a ref. |
| `E005` on a prompt that mentions a named studio | Named-style copyright block | Describe the aesthetic instead of saying e.g. "Robot Chicken style" / "Studio Ghibli style" |
| `E006` "Reference audio requires at least one reference image or video" | `reference_audios` alone | Always pair with at least one `reference_images` or `reference_videos` entry |
| `E006` on `duration < 4` | Seedance min duration | Use ≥4s; `docs/reference/timeline/models.md` lists 1s but server rejects it |
| "may be related to copyright restrictions" error | Recognizable politician likeness in a ref | Use silhouette / symbolic imagery / caption-only — see Section 3c |
| `E003` "Service is currently unavailable due to high demand" on retry loop | Genuine Seedance capacity issue | Wait 30+ min; or try `seedance-2.0` (different pool, ~5x cost). Sometimes the request hash routing helps — slight prompt tweaks can land on a less-loaded shard. |
| B-roll comes out as static slideshow | Reference image anchors model too hard | Lead prompt with `"FULLY ANIMATED, CONTINUOUS MOTION THROUGHOUT"`; single subject; consider motion-blur scene refs |
| Voice levels uneven across cuts | No normalization | `python scripts/polish_audio.py` after pipeline |
| Robot's chest text changes every cut | Stylized text drift | Specify `"<robot>'s chest sign is blank — no text"` in every clip prompt |

---

## 10. Tooling reference

| Script | Purpose |
|---|---|
| `scripts/batch_image_gen.py` | Parallel image generation across `gpt-image-2` and `nano-banana-2` from a JSON manifest |
| `scripts/asset_pack_push.py` | Upload a local asset directory to GCS as a named pack |
| `scripts/asset_pack_pull.py` | Download a pack from GCS to `runs/asset-packs/<name>/` |
| `scripts/analyze_news_clip.py` | Gemini extraction of speaker timestamps from a generated clip (for voice extraction) |
| `scripts/critique_clip.py` | Gemini critique of a single clip against a brief |
| `scripts/critique_full_video.py` | Gemini holistic critique of an assembled video |
| `scripts/polish_audio.py` | EBU R128 loudnorm pass + re-concat |

---

## 11. See also

- `docs/reference/timeline/format-reference.md` — full timeline schema
- `docs/reference/timeline/models.md` — per-model parameters and constraints
- `docs/workflows/music-video/` — sister workflow (different shape, same pipeline)
