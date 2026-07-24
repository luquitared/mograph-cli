# voice-via-audio-ref

By generating a clean line with Gemini 3.1 Flash TTS and passing that WAV to Seedance as `reference_audios`, you get noticeably better Seedance audio. On longer clips with a lot of narration, Seedance's bare-prompt audio tends to garble — words mush together, sentences slop into each other, the take is unusable. Handing it a reference WAV of the exact line fixes that. This workflow demonstrates the technique simply.

It's also the cure for the other common Seedance audio failure: flat, emotionless dialogue on short clips. Same fix, same mechanics.

Pair the reference WAV with a `reference_images` of the character — Seedance rejects audio-only refs with E006.

The reference audio can come from anywhere clean: Gemini 3.1 Flash TTS, ElevenLabs, an extracted WAV from a prior generation, even a recorded line. This demo uses Gemini 3.1 because it's deeply controllable via inline `[tag]` audio tags and `voice_prompt` direction.

## When to reach for this

- **Long-narration clips coming out garbled / sloppy.** Seedance loses the plot when it has to invent and pace a long line at the same time. Handing it a pre-paced reference removes one of those jobs.
- **Flat or emotionless dialogue on shorter clips.** The reference carries the emotional arc into Seedance's take.
- **You want deterministic control** over the voice personality, accent, or pacing.

Works best on **non-photoreal characters** (claymation, 2D, paper-cutout, low-poly 3D) where lip-sync expectations are loose enough that the Seedance-rendered mouth doesn't have to perfectly match the audio.

If lip-sync precision matters more than voice quality, prefer overlaying TTS on top of Seedance instead — but in our testing on cartoon characters, the overlay approach produced noticeably worse results than letting Seedance generate audio guided by the reference. Reference audio wins on perceived integration.

## The demo

A claymation chess player gloats at his opponent. The reference audio is a Gemini 3.1 TTS take of the line. Seedance produces a video where the chess player speaks in a voice that matches the reference's theatrical, dry delivery.

Files shipped with the demo:

- `assets/villain_voice.wav` — 24kHz mono WAV, Gemini 3.1 Flash TTS, voice `Puck`, the line `"Oh, you really thought you could outrun me? [laughs] That's adorable."`
- `assets/villain_ref.png` — a still frame of the claymation character (required by Seedance to accept audio refs)
- `examples/demo.json` — the timeline that wires them into a Seedance clip

```bash
python scripts/run.py docs/workflows/voice-via-audio-ref/examples/demo.json --stage final
# → runs/voice-via-audio-ref-demo/videos/villain_clip.mp4
```

Listen to the output. The Seedance-generated audio should sound recognizably like the reference WAV — theatrical, dry, with that short clipped laugh between sentences — not like Seedance's typical emotionless dialogue.

## Adapting it to your own scene

Three things to change:

1. **The reference audio.** Generate one with Gemini TTS:

   ```python
   from tts.gemini_tts import GeminiTTS
   from pathlib import Path
   GeminiTTS().synthesize_to_file(
       text="Your line here. [whispers] With expressive tags.",
       voice_name="Puck",  # or any voice from docs/reference/tts-voices.md
       voice_prompt="Optional Director's Notes: tone, pace, accent.",
       output_path=Path("assets/my-project/my_voice.wav"),
       output_format="wav",
   )
   ```

   Or extract a clean 5–10s WAV from any source with `ffmpeg -i src.mp3 -ar 24000 -ac 1 dest.wav`.

2. **The reference image.** Either generate a still of the character (Nano Banana Pro, GPT-Image-2) or extract a frame from a prior Seedance clip. Style must match the target — photoreal refs trip E005.

3. **The Seedance prompt.** Describe the character + the exact line spoken. Reference the audio explicitly with `[Audio1]` and the image with `[Image1]` so Seedance knows what they're for. Keep duration ≥ 4s and ≤ 15s.

## Hard constraints

- `reference_audios` alone fails E006 — always pair with at least one `reference_images` or `reference_videos`.
- Photoreal-human reference images trip E005. Stylized refs (claymation, 2D, etc.) pass.
- Reference audio must be a real audio file path. The current timeline schema doesn't support `{"ref": "<tts-clip-id>"}` on `reference_audios` — you must pre-generate the WAV.
- Seedance silently truncates prompts past 2000 chars (general project gotcha).

## Cost

- 1 × 8s Seedance fast 480p with refs ≈ **$0.88** per take.
- Generating the reference WAV with Gemini 3.1 Flash TTS is free at the time of writing.
