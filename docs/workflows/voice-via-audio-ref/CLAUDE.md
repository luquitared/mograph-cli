# voice-via-audio-ref — agent notes

Read this when the user reports that Seedance dialogue sounds emotionless or wants deterministic control over a non-photoreal character's voice. For human-facing strategy, see `README.md`.

## What this workflow is

A single-clip demonstration that passing a clean reference audio (Gemini 3.1 Flash TTS in the shipped example) plus a character still as `reference_images` + `reference_audios` to Seedance produces dramatically better audio than Seedance's bare-prompt dialogue. The output is Seedance-generated audio that has taken on the reference's timbre and cadence — not the reference audio overlaid on muted video.

**This workflow does NOT do TTS-over-video lip-sync.** That approach was tested and produced worse results than reference_audios for non-photoreal characters. If the user explicitly wants overlay, point them at the standard narration pattern (`narration-explainer/`) instead and warn them about lip-sync drift.

## When this applies

- Non-photoreal characters (claymation, 2D, paper-cutout, low-poly 3D, anime). Lip-sync expectations need to be loose.
- Short clips (< 15s). For multi-clip voice consistency, also see `news-video/` which uses the same reference_audios feature for cast continuity.
- User wants voice character control (theatrical, accented, whispery, etc.) that bare Seedance prompts don't give.

## How to drive

```bash
# Run the shipped demo as-is to confirm the setup works:
python scripts/run.py docs/workflows/voice-via-audio-ref/examples/demo.json --stage final

# To adapt to a new line, you need to (re)generate the reference WAV first.
# Inline Python is fine — no script needed:
python -c "
from tts.gemini_tts import GeminiTTS
from pathlib import Path
GeminiTTS().synthesize_to_file(
    text='Your line. [excited] With tags.',
    voice_name='Puck',
    voice_prompt='Director notes here.',
    output_path=Path('assets/<project>/voice.wav'),
    output_format='wav',
)
"
```

Use `scripts/run.py`, not `pipeline.py` directly — keeps each run in a stable `runs/<slug>/`.

## Defaults — pick these

- Video: `seedance-2.0-fast` at 480p, 16:9, `generate_audio: true` (we want Seedance audio, just guided by the reference).
- Reference WAV: 24kHz mono, 5–15s. Gemini 3.1 Flash TTS via `tts/gemini_tts.py` writes exactly this format.
- Reference image: stylized to match the target. Extract from a prior clip with `ffmpeg -ss 2 -i src.mp4 -vframes 1 -q:v 2 dest.png`, or generate fresh.
- No narration track. The point is to compare Seedance's voice quality with and without the audio ref; adding a TTS overlay defeats the point.

## Prompt skeleton

```
<style descriptor>. <character description, referencing [Image1]>.
<scene action>, mouth visibly moving with each syllable, and delivers
exactly: '<the line>'. <delivery beats>. <camera/lighting>.
Audio: match the voice timbre and cadence of [Audio1] — <restate emotional
arc of the line>.
```

The `[Image1]` and `[Audio1]` references explicitly bind the model's attention to the refs. Without them Seedance still uses the refs but less reliably.

## Critical rules

- `reference_audios` REQUIRES `reference_images` (or `reference_videos`). E006 otherwise. ([[project_seedance_audio_ref_requires_image]])
- Photoreal-human reference images trip E005. Use stylized refs only.
- Seedance prompt is silently truncated past 2000 chars. ([[project_replicate_2000_char_prompt_truncation]])
- Avoid stereotyped cartoon-villain visuals — they trip the copyright/likeness filter even without naming a studio. ([[project_seedance_cartoon_villain_trope]])
- Reference audio must be a real file path. The timeline schema's `reference_audios` is `List[str]` only — no `{"ref": "<clip-id>"}` support. If a user wants a TTS-clip-as-ref pattern, that's a schema change request.

## Expected failure modes

- **Reference voice doesn't carry through:** Try a longer reference WAV (closer to 10–15s), or restate the emotional arc more explicitly in the prompt's "Audio:" suffix.
- **Lip-sync looks off:** Expected — this workflow trades lip precision for voice quality. Use a less mouth-detailed style if it's distracting.
- **Moderation hit:** Check the prompt for stereotype tropes and the reference image for photoreal humans / known faces.
