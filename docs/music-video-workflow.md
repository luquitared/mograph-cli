# Music Video Workflow

End-to-end recipe for generating a stylized music video from an audio file
using Gemini 3.1 Pro (audio analysis) + Seedance 2.0 (video gen) + ffmpeg
(assembly).

## Inputs

- A music file — mp3 / wav / anything ffmpeg can read
- `.env` with `GOOGLE_API_KEY` and `REPLICATE_API_TOKEN`
- A creative brief from the user (style + character + scenes + avoids) —
  gathered in Step 2.5

## Outputs

- `<song>_timeline.json` — structured analysis (Gemini 3.1)
- `<name>-music-video.json` — mograph timeline
- `<final>.mp4` — assembled music video

## Steps

### 1. Analyze the song with Gemini 3.1

```bash
python analyze_music.py path/to/song.mp3 > <song>_timeline.json
```

> ⚠️ `analyze_music.py` writes JSON to **stdout** — always redirect or tee.
> Name the output song-specifically (e.g. `im_hot_timeline.json`) so it
> doesn't clobber an older `music_timeline.json` from another project.

Uses `gemini-3.1-pro-preview` — the only Gemini 3.1 variant that accepts
audio+structured-output. Returns a schema with `summary`, `sections`,
`beats`, `transitions`, `vocal_events`. Takes ~1 min per 3 min of audio.

Read the output. Scan `vocal_events` for specific lyric references
(places, people, situations) — each is a candidate scene.

### 2. Design the clip breakdown

Cut by musical sense, not equal lengths:

- Align clip boundaries to section boundaries (`sections[]`) and
  vocal-phrase boundaries (`vocal_events[]`)
- Target **5–9s per clip**
- **Seedance gen duration (`source.duration`) must be 4–15 integer
  seconds.** Below 4 hits E006.
- For shorter playback (e.g. a 2.5s phrase), use `source.duration: 4`
  (integer, the gen length) paired with `clip.duration: 2.5` (float,
  the playback length) on the clip wrapper — `assemble_music_video.py`
  trims the excess.
- One scene per clip; aim for variety — avoid putting the whole song in
  one setting.
- For beat-sync within a clip, write timestamped shot changes into the
  prompt text (e.g. `[0-2s] X. [2s CUT] Y. [4s CUT] Z.`) — Seedance
  honors these.

### 2.5. Get the creative brief from the user

**Do not skip.** Without an explicit brief, agents default to whatever
was in the last timeline they saw — body type, outfit, face, vibe all
leak through. Ask up front, even if it feels like too many questions.

Gather, one field at a time:

- **Style.** A generic aesthetic description — cel-shaded anime,
  claymation stop-motion, flat 2D adult-sitcom cartoon, hand-drawn
  watercolor, retro VHS / early-90s broadcast, 3D low-poly, comic-book
  halftone, pixel art, paper-cutout collage. Never name a studio,
  franchise, or specific show.
- **Character.** Whatever description the user provides. Capture any
  specific features they mention (skin, hair, facial hair, glasses,
  signature outfit) and the **distinguishing feature** that makes them
  them (e.g. "chains so huge his neck is hidden", "always holding
  an ice cream", "permanently crying one anime tear"). Do not
  interrogate the user for slots they didn't mention — fill gaps with
  generic, neutral descriptors. Never carry character details over
  from a prior project's timeline; each song gets a fresh character.
- **Scene concepts.** Specific settings, jokes, or callbacks tied to the
  lyrics. Pull candidates from Step 1's `vocal_events`.
- **Recurring motifs.** Things that should appear in *multiple* clips,
  not just one (e.g. "anime girls running after him" → show up in 3+
  clips, not a single scene).
- **Hard avoids.** Off-limits subject matter or imagery.
- **Quality tier.** Draft (480p, `seedance-2.0-fast`, ~$0.06/s) or final
  (720p, `seedance-2.0`, ~$0.17/s) — see cost table. Default to draft
  unless user says otherwise.

If the user handed you a **photo of a real person** as character
reference, you cannot use it as `reference_images` — E005 blocks every
photoreal face ref. Tell the user explicitly: *"The photo can't be fed
into Seedance. I'll describe them in text using the slots above — can
you confirm body type / hair / face / outfit?"*

Record the brief as a `_brief` key at the top of the timeline JSON so
it ships with the artifact.

### 3. Build the mograph timeline

The timeline is a JSON file that describes one video track (the clips
to generate) and one audio track (the song). Here's the **shape** — fill
in the slots from your Step 2.5 brief and Step 2 clip plan; do not
paste details from another project's timeline, they'll leak.

```jsonc
{
  "_brief": "<one-paragraph snapshot of the user's creative brief>",
  "version": 1,
  "project": {
    "name": "<Song Title Music Video>",
    "aspect_ratio": "16:9",
    "resolution": "720p"
  },
  "defaults": {
    "video": {
      "model": "seedance-2.0-fast",  // or "seedance-2.0" for final quality
      "resolution": "480p",          // or "720p" for final
      "aspect_ratio": "16:9",
      "generate_audio": false        // required — song goes on audio track
    }
  },
  "tracks": [
    {
      "id": "visuals",
      "type": "video",
      "clips": [
        {
          "id": "<short_clip_id>",
          "duration": <playback_seconds_float>,   // final played length
          "source": {
            "type": "video",
            "duration": <gen_seconds_int_4_to_15>, // Seedance gen length
            "prompt": "<see prompt structure below>"
          }
        }
        // ...one per planned clip
      ]
    },
    {
      "id": "song",
      "type": "audio",
      "volume": 1.0,
      "clips": [
        { "id": "bgm", "source": { "type": "file", "path": "<song.mp3>" } }
      ]
    }
  ],
  "output": {
    "format": "mp4",
    "audio_mix": { "narration": 0.0, "music": 1.0, "sfx": 0.0 }
  }
}
```

#### Prompt structure per clip

Each prompt has four blocks. Write them in this order — consistency
across clips is what gives the video a coherent look.

1. **Style descriptor** — the aesthetic from the brief, generic
   wording. *Example for anime:* "cel-shaded anime style, sharp line
   art, large expressive eyes, vibrant flat colors, hand-drawn feel,
   dynamic action-lines on motion."
2. **Scene with timestamped cuts** — the shot sequence for this clip,
   with beat-aligned CUTs matching the song's rhythm at that window.
3. **Character description** — **every slot from Step 2.5's structured
   character** (body type, skin, hair, face, outfit, distinguishing
   feature). Repeat it verbatim in every clip — Seedance does not
   carry character state across clips.
4. **Atmosphere / lighting / palette** — one line to anchor mood.

Conventions that are non-negotiable:

1. **No photoreal human `reference_images`.** Seedance moderation blocks
   them (E005). Character lives in prompt text only. See
   [`seedance-moderation-findings.md`](../seedance-moderation-findings.md).
2. **No named studios / franchises / celebrities / specific IP in
   prompts.** Hits the copyright filter. Known triggers: "Vin Diesel"
   + racing aesthetic cues (stripes, neon underglow, big spoiler), named
   currency denominations ("$20 bills" — use "bags of money"), named
   studio styles ("Aardman-style", "Ghibli-style" — use generic).
3. **`source.duration` is integer 4–15.** `clip.duration` is a separate
   float for playback after assembly. Below 4 = E006.
4. **`generate_audio: false`** in video defaults — so Seedance's model
   audio doesn't fight the song.
5. **Audio track** — song on an `audio` track, `type: "file"`,
   `volume: 1.0`. `output.audio_mix.music: 1.0, narration: 0.0`.

> ⚠️ **Project rule:** before running the pipeline, show the full
> timeline JSON to the user for approval. This is enforced across the
> repo (see auto-memory `feedback_check_timeline`). Retry runs (Step 5)
> are recovery work and don't need a fresh approval cycle.

Working examples exist in the repo if you want to see real timelines
in context: [`liquidated-music-video.json`](../liquidated-music-video.json)
(full, 26 clips) and [`liquidated-retry.json`](../liquidated-retry.json)
(retry shape). **Do not copy character, style, or scene text from them**
— use them only to sanity-check field shapes against your own content.
Schema specifics: [`format-reference.md`](timeline/format-reference.md),
[`timeline.schema.json`](timeline/timeline.schema.json).

### 4. Run generation

```bash
python pipeline.py --timeline-file <name>-music-video.json --dry-run
python pipeline.py --timeline-file <name>-music-video.json --stage final \
    2>&1 | tee /tmp/<name>_run.log
```

Behavior:

- Clips run in parallel (one Replicate prediction per clip).
- **E005 moderation errors auto-retry up to 3 times within the same run.**
  Usually benign. But: an unlucky E005 retry loop can burn 10–15 min per
  clip and LOOK like the pipeline is hung — see Step 5 "stuck clip"
  section if you see the run sit at N-1/N for >5 min.
- **Copyright errors (no E-code) do NOT auto-retry.** String contains
  `"output video may be related to copyright restrictions"`. Fail fast;
  need a rewrite.
- **E006 errors (duration out of range) do NOT auto-retry.** Fix by
  raising `source.duration` to ≥4.
- On success the pipeline prints
  `Timeline execution complete. Output: runs/<Run_Dir>` as its final
  line — grab that path for Step 6.

### 5. Handle failures

Three failure modes, same recovery shape:

1. **Copyright error** — fail fast, needs a prompt rewrite.
2. **E006** — fix `source.duration` to ≥4 (plus float `clip.duration`
   to keep playback tight).
3. **Stuck clip (E005 retry loop)** — the pipeline sits at
   N-1/N done for many minutes on a single clip. Kill it
   (`pkill -f pipeline.py`) and treat the laggard like a copyright
   failure. The offending clip usually has a combination of factors
   that reads as photoreal: extreme human close-ups (face, hand), body
   gestures ("hands up", "pointing"), and prompt language that
   personifies the subject too literally. Reframe with more composition
   distance and less isolated human anatomy.

Build a retry timeline containing ONLY the failing clip(s). Same shape
as Step 3 (all top-level blocks), one video track, the failing clips
with reworked prompts.

```bash
python pipeline.py --timeline-file <name>-retry.json --stage videos
```

**Reframe, don't soften.** If a prompt keeps failing after adjective
tweaks, change the scene idea entirely — different action, different
composition, different focal subject.

The retry pipeline writes each clip as `<clip_id>.mp4` in its own
`runs/<Retry_Run>/videos/` directory — same filename shape as the main
run, which is what makes Step 6 assembly work. Note the retry run
directory path; you'll pass it as `--extra-videos-dir` in Step 6.

### 6. Assemble the final video

The mograph `final` stage currently doesn't trim by float
`clip.duration` or mux `file`-source audio tracks on music-video
timelines (no narration track). Use the assembly script:

```bash
python assemble_music_video.py \
    <name>-music-video.json \
    runs/<Main_Run_Dir> \
    <name>_music_video.mp4 \
    --extra-videos-dir runs/<Retry_1_Run>/videos \
    --extra-videos-dir runs/<Retry_2_Run>/videos
```

`<Main_Run_Dir>` is what the pipeline printed at the end of Step 4.
Later `--extra-videos-dir` flags win, so retries listed last override
the main run's version of a clip.

The script: reads the timeline's video track → finds each clip by its
`<clip_id>.mp4` filename in the run dirs (later `--extra-videos-dir`
wins) → trims to `clip.duration` → concatenates in order → muxes with
the audio track's `file` source at volume 1.0.

## Rough costs

Per second of generated video, flat pricing, no refs:

| Model | Resolution | Cost/s | Notes |
|---|---|---|---|
| `seedance-2.0-fast` | 480p | **$0.06** | Draft / iteration. Soft image, fine for previews. |
| `seedance-2.0-fast` | 720p | **$0.13** | Same model, sharper. Good middle ground. |
| `seedance-2.0` | 720p | **$0.17** | Final quality — better motion and character consistency. |
| `seedance-2.0` | 480p | $0.07 | Rarely useful — 720p is the reason to pay the premium. |

Example totals (before retries):

| Song length | Clips × avg gen | Draft (480p fast) | Final (720p full) |
|---|---|---|---|
| 30s | 5 × 6s = 30s | $1.80 | $5.10 |
| 30s | 8 × 4s = 32s | $1.92 | $5.44 |
| 180s | 26 × 7s = 182s | $10.92 | $30.94 |

You cannot generate Seedance clips shorter than 4s — for many short
cuts, `source.duration: 4` and trim via float `clip.duration`.

## Gotchas at a glance

| Symptom | Cause | Fix |
|---|---|---|
| `E005` on every clip | Photoreal human `reference_images` | Drop refs, describe in text, stylize |
| `E005` recurring on some clips | Prompt reads as photoreal (extreme face/hand close-ups, body gestures) | Strengthen stylized descriptors, add composition distance |
| Pipeline sits at N-1/N for >5 min | One clip in E005 retry loop | Kill pipeline, retry that clip with a reframed prompt |
| `E006` on some clips | `source.duration < 4` | Raise to ≥4, use float `clip.duration` to trim playback |
| `copyright restrictions` (no E-code) | Named franchise / celebrity / real-world IP in prompt | Use generic descriptors, reframe the visual |
| Character attributes from a prior project leaked into this one | Copy-paste from another timeline's prompts | Write the character fresh from Step 2.5's brief; don't reuse prompt text across projects |
| Final mp4 longer than the song | `final` stage didn't trim per `clip.duration` | Use `assemble_music_video.py` |
| Final mp4 has no audio | `final` stage didn't mux `file` audio track | Use `assemble_music_video.py` |

## Files this workflow uses

- [`analyze_music.py`](../analyze_music.py) — root — Gemini 3.1 Pro
  audio analyzer (writes JSON to **stdout** — always redirect or tee)
- [`assemble_music_video.py`](../assemble_music_video.py) — root —
  ffmpeg trim + concat + mux
- [`timeline/format-reference.md`](timeline/format-reference.md) —
  full timeline schema
- [`timeline/models.md`](timeline/models.md) — Seedance / Nano Banana /
  GPT Image parameters
- [`../seedance-moderation-findings.md`](../seedance-moderation-findings.md)
  — moderation test matrix
- [`../liquidated-music-video.json`](../liquidated-music-video.json) and
  [`../liquidated-retry.json`](../liquidated-retry.json) — working
  examples for field-shape sanity-checking only; do not copy content
