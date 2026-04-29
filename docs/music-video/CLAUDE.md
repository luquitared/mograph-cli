# music-video — agent notes

Read this when the user wants to turn an audio track (mp3 / wav) into a
stylized music video — Gemini 3.1 Pro analyzes the song into sections,
beats, and vocal events, then Seedance generates one clip per
section/phrase. For the full recipe, see `README.md`.

## How to drive this workflow

```bash
# 1. Analyze the song (Gemini 3.1 Pro on audio)
python analyze_music.py path/to/song.mp3 > <song>_timeline.json

# 2. Get a creative brief from the user (don't skip — see Section 2.5
#    of README.md for the checklist)

# 3. Hand-edit the timeline to translate the analysis into video clips

# 4. Validate, then run
python scripts/timeline_validate.py <song>-music-video.json
python scripts/run.py <song>-music-video.json
```

`scripts/run.py` keeps everything in `runs/<slug>/`. Don't call
`pipeline.py` directly.

## Defaults

- Video: `seedance-2.0` (regular, NOT fast — quality matters here) at
  480p, 16:9
- TTS: not used in this workflow

## Critical rules — different from other workflows

- **Cut by musical sense, not equal lengths.** Align clip boundaries to
  `sections[]` and `vocal_events[]` from the analysis JSON. Target 5–9s
  per clip.
- **WPS 2.5 doesn't apply** — there's no spoken dialogue to budget.
  Clip length is driven by song structure.
- **Seedance gen `duration` must be int 4–15.** For shorter playback
  (e.g. a 2.5s phrase), use `source.duration: 4` (gen length, integer)
  paired with `clip.duration: 2.5` (float, playback length on the
  wrapper). The assembler trims excess.
- **One scene per clip; aim for variety.** Avoid putting the whole song
  in one setting.
- **Beat-sync within a clip:** write timestamped shot changes into the
  prompt text — `[0-2s] X. [2s CUT] Y. [4s CUT] Z.`. Seedance honors
  these inside a single clip.

## The analyze step is non-negotiable

The user's input is a song. They want a video that fits *that specific
song*. Don't skip the `analyze_music.py` step and improvise — read the
returned `sections`, `beats`, `vocal_events` and let them shape the
clip breakdown. Vocal events surface concrete lyric references
(places, people, situations) — each is a candidate scene.

## The creative brief is non-negotiable

Without an explicit brief from the user (style + character + scenes +
avoids), agents default to whatever and produce generic output. Ask:

1. **Style:** photoreal, anime, claymation, 2D illustrated, 3D, mixed?
2. **Recurring character/subject:** is there a protagonist? What do they
   look like?
3. **Scenes:** any specific imagery the user already has in mind for
   particular lyrics?
4. **Avoids:** styles, content, or imagery to steer clear of?

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Music timeline JSON gets clobbered | Multiple songs writing to `music_timeline.json` | Always name song-specifically: `analyze_music.py x.mp3 > x_timeline.json` |
| Clips feel generic | No creative brief gathered | Ask the user the 4 questions above before designing clips |
| Visual continuity weak across cuts | Each clip prompt independent | Use `reference_images` chaining or first/last-frame extraction across consecutive clips (see `docs/timeline/patterns.md` on chaining) |
| Long clips look static | Seedance over-stabilizes 15s clips | Use timestamped shot changes inside the prompt; or split into shorter clips |

## Files in this workflow

- `analyze_music.py` (project root) — Gemini 3.1 Pro audio analysis
- `assemble_music_video.py` (project root) — beat-synced ffmpeg assembly
  (handles the float `clip.duration` trim)
- `render_music_cuts.py` (project root) — render-and-cut helper
