# Known Issues & Field Notes

Bugs, footguns, and measured model behaviour found while building real videos.
Each entry has a repro, a root cause with file references, and (where known) a fix.

Case study throughout: the **Kalmari squid ad** (2026-07-24) — a 25.5s vertical
(9:16, 720p) narrated ad, 5 clips, `seedance-2.0` + Gemini TTS, built in
`runs/kalmari-squid-ad/`. `runs/` is gitignored, so the findings live here.

---

## 1. `fit_to` silently resolves to 0.0 on resume → truncated audio

**Severity: high.** The run reports success and writes a playable `final.mp4`
with narration cut off. Nothing in the exit code says otherwise.

### Symptom

```
Fit adjustment failed: float division by zero     (× once per fitted clip)
Timeline execution complete. Output: runs/<slug>
[run] 5/5 clips complete
```

Exit code `0`. The resulting `final.mp4` had **27.2s of video against 34.3s of
narration** — roughly 7 seconds of voiceover silently discarded.

`timing.json` from the bad run is the tell — every value zeroed:

```
total_duration 0.0
vid-1-narration   start=0.00 raw=0.00 final=0.00
vid-1             start=0.00 raw=5.00 final=0.00 fit=True
...
```

### Repro

1. Run a timeline with `narration` (or explicit `fit_to`) to completion so TTS
   is cached in `runs/<slug>/audio/`.
2. Re-run with `--force-clip <some-video-clip>` (or any resume that does not
   regenerate TTS).
3. Every `fit_to` target resolves to `0.0`; the fit is skipped; audio is
   truncated to the unfitted video length.

### Root cause

The layout is computed from the in-memory `results` map, not from disk:

- `timeline/executor.py:1042` — `layout = compute_timeline_timing(timeline, results)`
- `timeline/tts_gen.py:165` — a duration is attached to the `NodeResult` **only**
  on the fresh-synthesis path (`probe_duration_async` immediately after
  `_synth()`). There is no branch that re-probes an already-existing WAV/MP3 on
  resume, so a skipped TTS node never enters `results` with a duration at all.
- `timeline/timing.py:44` `_get_raw_duration()` — with no `NodeResult` duration,
  a `TTSSource` falls through every `isinstance` branch to the final
  `return 0.0` at **`timeline/timing.py:96`**:

  ```python
  # TTSSource or unknown — rely on NodeResult (already checked above)
  if isinstance(clip.duration, (int, float)):
      return float(clip.duration)
  return 0.0
  ```

- Each video clip's `fit_to` target therefore has `final_duration == 0.0`, so the
  clip is marked `needs_fit=True` with `target_duration=0.0`.
- `timeline/fitter.py:79` — `speed_factor = raw_duration / target_duration`
  → `ZeroDivisionError`.
- `timeline/executor.py` catches fit exceptions, logs them, and **continues**.
  Clips keep their raw durations and assembly proceeds against a timeline that
  is shorter than the narration.

### Workaround

Delete the cached audio to force TTS to regenerate in-process:

```bash
rm -rf runs/<slug>/audio runs/<slug>/final
python scripts/run.py <timeline.json> --stage final
```

Fresh `NodeResult`s carry real durations, the layout resolves, and the fit
applies normally (observed speed factors 1.05–1.34× on the Kalmari ad).

### Fixed 2026-07-24 (partially)

Two of the three suggested changes are now in. Hit again on the ad-creator
Kalmari run, where it fires on **every** ad rather than occasionally: that
product renders images as its own approval gate and then always runs the video
stage with `--resume-dir`, so every TTS node is a resumed node. Narration came
out 26.08s against 20.18s of video — the whole last line gone.

1. **Re-probe on resume — done.** The real culprit was
   `timeline/executor.py::_load_existing_results()`, which hardcoded
   `duration=None` for every resumed image, video, and audio node (not
   `tts_gen.py`, which populates duration correctly on the fresh path). It now
   ffprobes each file via `_probe_or_none()`.
2. **Fail loudly — done.** `timeline/fitter.py::_apply_speed()` raises a
   descriptive `ValueError` when `target_duration <= 0` instead of leaking a
   bare `ZeroDivisionError`.
3. **Treat fit failure as a run failure — still open.** A fit exception is still
   caught and logged, and assembly proceeds. With (1) fixed this should no
   longer trigger in practice, but a genuinely unfittable clip would still ship
   quietly.

**Diagnosis note.** The first read of this on the ad-creator run blamed a
declared `clip.duration` making `_get_raw_duration()` return a length the file
didn't actually have. That is a real footgun and worth avoiding (see §10), but
it was not this failure — the `float division by zero` lines in the log are the
signature of a 0.0 fit target, and predicted a 21.9s video where the actual was
20.18s. Match the log line, not the plausible story.

### Always verify before shipping

Fit failure is invisible in the pipeline's own output. Check the streams:

```bash
ffprobe -v error -select_streams v -show_entries stream=duration -of csv=p=0 final/final.mp4
ffprobe -v error -select_streams a -show_entries stream=duration -of csv=p=0 final/final.mp4
# and compare against the sum of runs/<slug>/audio/*narration.mp3
```

Audio duration should equal the narration total. On the fixed Kalmari run:
audio `25.52s` = narration total `25.52s`, video `25.29s`.

---

## 2. Seedance output filenames collide when two prompts share an opening

**Severity: high.** Destroys paid generations and can leave a corrupt file.

### Symptom

```
Video generation failed for clip vid-2: [Errno 2] No such file or directory:
  '.../videos/fully-animated-continuous-motion-throughout-same-style-as-im-bytedance-seedance-2.0-6s.mp4'
  -> '.../videos/vid-2.mp4'
Video generation failed for clip vid-3: moov atom not found
```

### Root cause

Downloaded clips are named from a ~60-character slug of the **prompt text**.
`vid-2` and `vid-3` both began:

> `FULLY ANIMATED, CONTINUOUS MOTION THROUGHOUT. Same style as [Image1], same room as [Image2]...`

Both slugged to the identical filename and, running concurrently, wrote to the
same path. One clobbered the other; the survivor was truncated
(`moov atom not found`). Two paid generations lost.

### Workaround

Make the first ~60 characters of every prompt unique. On the Kalmari ad:

```
FULLY ANIMATED, CONTINUOUS MOTION THROUGHOUT — DESK MONTAGE. ...
FULLY ANIMATED, CONTINUOUS MOTION THROUGHOUT — BOARD CRANE SHOT. ...
```

### Suggested fix

Name downloads by `clip_id` (already unique and validated), or append a short
hash of the full prompt. The prompt slug is fine as a *label*, not as a key.

---

## 3. `scripts/run.py` stages the timeline, breaking relative reference paths

**Severity: medium.** Fails fast and loudly, so it costs a run, not money.

### Symptom

```
error: [tracks[1].clips[4].source.first_frame] File not found: runs/<slug>/refs/endcard.png
Timeline validation failed with 1 error(s)
```

…even though the file exists and `scripts/timeline_validate.py` passes on the
original timeline.

### Root cause

`scripts/run.py` copies the timeline to `runs/.staging/<name>.json` before
invoking `pipeline.py`. Relative paths resolve against the timeline's location,
which is now `runs/.staging/`, not the project dir.

### Workaround

Use **absolute paths** for `reference_images`, `reference_audios`,
`reference_videos`, and `first_frame`/`last_frame` in any timeline run through
`scripts/run.py`. This matches the existing guidance in
`project_ig_download_and_fastcut_clone` memory.

---

## 4. The image verifier rejects good assets

**Severity: medium.** Wastes money and can discard the best candidate.

On the Kalmari den reference, `generation/batch_img.py --verify` (OpenAI vision,
5 attempts) rejected **5 of 5** candidates for reasons like:

- "image shows 6 monitors … prompt requested eight"
- "underwater lighting introduces a teal/cyan ambient colour"
- "cards show ruled lines … not completely plain as requested"

All five went to `runs/<slug>/failed_images/`. **Attempt 1 was exactly on
brief** — eight monitors in a curved arc, acid-lime, blank cards — and was
promoted by hand.

### Guidance

- Treat verifier output as advisory. **Look at the rejects yourself** before
  paying for re-rolls; they are kept in `failed_images/`.
- Verification earns its keep on **text-bearing** images (it correctly caught a
  clipped disclaimer on the end card and fixed it in one retry). It is
  over-strict on compositional and colour criteria.
- Consider `--no-verify` for atmospheric/background plates and reserving
  verification for images with on-screen copy.

---

## 5. Environment footguns

| Issue | Symptom | Workaround |
|---|---|---|
| `.env` is not auto-loaded | `GOOGLE_API_KEY not set`, `REPLICATE_API_TOKEN not set` | Prefix commands with `set -a && . ./.env && set +a`. Only `mograf/cli.py:64` loads dotenv. |
| `generation/batch_img.py` run directly | `ModuleNotFoundError: No module named 'shared'` | `PYTHONPATH=$(pwd) python generation/batch_img.py ...` |
| `.env` shipped as mode `644` | world-readable secrets | `chmod 600 .env` (done 2026-07-24) |

A stale `GOOGLE_API_KEY` fails as `401 UNAUTHENTICATED` /
`ACCESS_TOKEN_TYPE_UNSUPPORTED`, and blocks **both** `nano-banana-2` and all
Gemini TTS. Test a key without spending:

```bash
curl -s -o /dev/null -w "%{http_code}\n" "https://generativelanguage.googleapis.com/v1beta/models?key=$KEY"
```

Note it must be sent as an API key (`?key=` or `x-goog-api-key`), **not** as
`Authorization: Bearer` — bearer returns 401 even for a valid key.

Fallback when Gemini is down: `nano-banana-pro` (Replicate) and `gpt-image-2`
(OpenAI) cover image generation. There is **no** TTS fallback —
`timeline/tts_gen.py` hardcodes Gemini in `TTS_MODEL_MAP`, so a dead Google key
blocks narration entirely.

---

## 6. Words-per-second: 2.5 is optimistic

Root `CLAUDE.md` gives **2.5 WPS** as the budgeting rule. Measured on this build
with voice `Puck` + inline `[bracket]` tags + an ad-narrator `voice_prompt`:

| Line | Words | Actual | WPS |
|---|---|---|---|
| "Somewhere in the dark, a squid is doing your homework." | 10 | 4.76s | 2.1 |
| "Eight arms, eight tabs, hunting every mispriced Kalshi market." | 9 | 5.52s | 1.6 |
| "Every pick, full thesis, scored in public — wins and losses." | 11 | 5.12s | 2.1 |
| "Lands in your Telegram. One tap, back to your calamari." | 10 | 4.48s | 2.2 |
| "Kalmari dot app. Your AI trades Kalshi while you feast." | 10 | 5.64s | 1.8 |

**Effective rate ≈ 1.9 WPS**, and as low as 1.6 on lines with heavy bracket
cues. Bracket tags buy expressiveness by adding pauses — they cost time.

**Budget expressive ad narration at ~1.8 WPS**, i.e. `target_seconds × 1.8`
words. The 2.5 figure is closer to right for flat, tag-free reads. Getting this
wrong is what created the 34.3s-of-narration-into-27s-of-video mismatch in §1.

---

## 7. Seedance behaviour notes

Observed on `seedance-2.0` @ 720p, `quality: "high"`, 9:16.

- **720p is the ceiling.** There is no 1080p on either `seedance-2.0` or
  `seedance-2.0-fast`. "Higher resolution" means `seedance-2.0` + `720p` +
  per-clip `quality: "high"`.
- **`quality` must be set per clip.** `defaults.video.quality` is ignored
  (warning only) — see `project_seedance_quality_per_clip_only`.
- **A reference image does not preserve rendered text.** The `phone-pick.png`
  composite had crisp, correct copy; Seedance re-rendered it into warped, mushy
  text in the output clip. Treat text in a ref as *art direction*, not as an
  asset that survives. For text that must stay legible, use a static end-card
  approach (§ below).
- **A locked `first_frame` + "camera absolutely locked off" holds text
  perfectly.** The end card (`vid-5`) came through pixel-clean — wordmark,
  tagline, URL, and disclaimer all intact. This is the reliable pattern for any
  shot that must carry copy.
- **A competing reference can hijack the shot.** `vid-3` was briefed as a crane
  up a wall of result cards, but with the den plate (dominated by glowing
  monitors) in `reference_images`, Seedance kept returning the desk. Dropping
  the den ref and writing explicit negatives — *"There are NO monitors, NO desk
  and NO keyboard anywhere in frame"* — produced the intended shot on the next
  try.
- **Character binding via a reference sheet works.** The squid stayed
  recognisably the same across three clips. Drift was limited to glasses frame
  weight and marking detail — acceptable, but it is drift.
- **Limb counts do not survive.** The mascot never reads as having eight arms in
  any shot, despite an explicit 4-view reference sheet. Do not write narration
  that asks the viewer to count something ("*eight* arms, *eight* tabs").
- **Humans are the weakest output.** The one human shot produced an elbow-less
  arm and a fused mitten hand — the single worst defect in the ad. Prefer
  hands-only/tight framing, or keep humans out of frame.

---

## 8. Adversarial QC beats friendly QC

Two Gemini video-understanding passes were run over the same finished ad
(`gemini-3.1-pro-preview`, video uploaded via `client.files.upload`).

| Pass | Framing | Result |
|---|---|---|
| `scripts/critique_clip.py` | "critique this against the brief" | **8/10**; only issue flagged was "minor animation stiffness" |
| Adversarial slop audit | "you are a hostile VFX supervisor; assume it is AI-generated; find every tell" | **slop 7/10, reads as "unmistakably" AI**; caught the critical hand defect, character drift, and text warping |

The friendly framing waved through a defect that would embarrass a paid
placement. **Always run a hostile pass before shipping.**

What made the adversarial pass work:

- Explicitly told the model the video is AI-generated and its job is to find
  tells, not to score against intent.
- A structured schema with per-finding `severity` **and** `viewer_noticeable`
  (`obvious_on_first_watch` / `noticeable_if_looking` / `only_frame_by_frame`),
  so cosmetic nitpicks sort below things a scrolling viewer would clock.
- Named failure-mode categories (anatomy, morphing, text garbling, temporal
  flicker, physics, unnatural speed, character inconsistency, texture mush,
  uncanny face, audio artifact).
- Targeted questions about known-fragile properties: limb count consistency,
  same-character-across-shots, verbatim transcription of all on-screen text.
- `"Do NOT invent problems that are not there"` to hold down false positives.

**Verify its findings before acting.** The audit reported the phone reading
`Entry 81c`; frame extraction showed a degraded `41c`. The specific claim was
wrong, but the underlying finding — the text is warped — was correct and more
serious than stated. Confirm each finding against extracted frames:

```bash
ffmpeg -v error -y -ss <t> -i final/final.mp4 -frames:v 1 frame.png
```

---

## 9. Kalmari ad — outstanding defects

Status as of 2026-07-24: assembled, in sync, **not yet fixed**.
Output: `runs/kalmari-squid-ad/final/final.mp4` (25.5s, 9:16, 720p).

| # | Defect | Beat | Severity |
|---|---|---|---|
| 1 | Human arm has no elbow; hand is a fused mitten on the tap | 4 (`vid-4`) | critical |
| 2 | Shot plays at **1.34×** (fit speed-up), so the "unbothered" joke reads hurried | 4 (`vid-4`) | major |
| 3 | Phone screen text warped/smeared despite a clean composite ref | 4 (`vid-4`) | major |
| 4 | Squid never reads as eight arms, but the VO says "eight arms, eight tabs" | 1–3 | major |
| 5 | Opens on an empty desk — squid not in frame for its own line | 2 (`vid-2`) | major |
| 6 | Mild character drift (glasses frame weight, markings) | 1–3 | minor |

Proposed remedy: re-render `vid-2` and `vid-4` (~$2). For `vid-4`, drop the full
human and shoot tight on plate + phone + a single hand. For `vid-2`, lock the
squid in frame with arms spread across the monitors so the line has something to
land on. Generate `vid-4` at a source duration close to its narration length so
the fit does not need to speed it up.

---

## 10. `source.duration` is the only length the model reads

**Severity: medium.** Costs a re-render and distorts pacing.

On the ad-creator Kalmari run every clip declared `"duration": 6` at the clip
level and left `source.duration` unset. Seedance never saw a request for 6s and
returned its **5s default** — four clips at 5.04s against a 24s plan.

Two distinct fields, easy to confuse:

| Field | Read by | Effect |
|---|---|---|
| `clip.source.duration` | the video model | how many seconds get generated |
| `clip.duration` | the assembler | how long the clip occupies the timeline |

### Guidance

- **Always set `source.duration`** (whole seconds, 4–15) when you want a
  specific shot length. `defaults.video.duration` works too.
- **Omit `clip.duration` on any clip carrying `narration`.** Left as `"auto"`
  the assembler measures the real file; declared, it trusts your number and
  computes the speed-fit against a length that may not exist. Combined with §1
  that compounds into truncated narration.
- Getting the requested length also keeps the fit speed factor near 1.0 — §9's
  defect 2 (a shot playing at 1.34× because the clip was much shorter than its
  narration) is the same root cause seen from the other side.

---

## See also

- `docs/reference/script-writer.md` — bracket-cue rules for expressive delivery
- `docs/reference/timeline/models.md` — per-model constraints and costs
- `docs/workflows/news-video/CLAUDE.md` — cast binding via reference sheets
- `docs/workflows/narration-explainer/CLAUDE.md` — `fit_to` shape and stage iteration
