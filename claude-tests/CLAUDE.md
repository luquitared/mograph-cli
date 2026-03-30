# E2E Pipeline Tests

Run all three pipeline modes for real (no mock) using a 2-scene explainer video. Launch 3 subagents in parallel.

## Prerequisites

- `.env` file at project root with: `REPLICATE_API_TOKEN`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `DEEPGRAM_API_KEY`
- All agents must source `.env` and export keys before running pipeline commands
- Test script: `tests/fixtures/e2e_test_script.json` (2-scene photosynthesis explainer)

## Agent 1: Script Mode (full pipeline)

Single command, runs all stages end-to-end.

```bash
source .env && export REPLICATE_API_TOKEN GOOGLE_API_KEY OPENAI_API_KEY ELEVENLABS_API_KEY DEEPGRAM_API_KEY
python pipeline.py --script-file tests/fixtures/e2e_test_script.json --stage final
```

Timeout: 10 minutes. Produces `final/final.mp4`, `final/final_with_sfx.mp4`, `final/final_images_only.mp4`.

## Agent 2: TTS-Only Mode (two steps)

**Step 1** — Generate TTS audio and timestamps:
```bash
python pipeline.py --tts-only --script-file tests/e2e_test_script.json --stage final
```
Note the run directory from output.

**Step 2** — Resume to produce final video:
```bash
python pipeline.py --resume-dir <RUN_DIR> --script-file tests/e2e_test_script.json --stage final
```

Timeout: 10 minutes for step 2. Produces same 3 final outputs.

## Agent 3: Voice Mode (four steps)

This is the most complex mode. The agent must read the transcript and build a timestamped script.

**Step 1** — Generate a voice recording using Gemini TTS (creates the test voice file):
```python
from tts.gemini_tts import GeminiTTS
from pathlib import Path

client = GeminiTTS()
text = (
    "Every single day, plants perform an incredible chemical reaction "
    "that powers nearly all life on Earth. "
    "That process is called photosynthesis, and without it, "
    "life as we know it simply would not exist."
)
client.synthesize_to_file(text=text, output_path=Path("tests/fixtures/e2e_test_voice.mp3"), voice_name="Kore", output_format="mp3")
```

**Step 2** — Run voice mode to transcribe:
```bash
python pipeline.py --voice-file tests/fixtures/e2e_test_voice.mp3
```
Note the run directory. This transcribes the audio via Deepgram and stops.

**Step 3** — Read `<RUN_DIR>/transcript.json` and create a script with correct timestamps.

The transcript contains word-level timestamps:
```json
{"word": "Every", "start": 0.4, "end": 0.8},
{"word": "Earth.", "start": 6.88, "end": 7.38},
{"word": "That", "start": 7.76, "end": 8.0},
{"word": "exist.", "start": 13.6, "end": 14.1}
```

Split at the natural sentence boundary (after "Earth."). Build a script where each scene has:
- `start_time` = first word's `start` timestamp in that segment
- `end_time` = last word's `end` timestamp in that segment
- `narrator` = the actual text from the transcript for that segment
- `visuals` array with `concept_name`, `image_prompt`, `animation_prompt`

Save as `tests/fixtures/e2e_test_voice_script.json`.

**Step 4** — Resume to produce final video:
```bash
python pipeline.py --resume-dir <RUN_DIR> --script-file tests/fixtures/e2e_test_voice_script.json --stage final
```

Timeout: 10 minutes. Produces same 3 final outputs.

## Expected Results

Each mode should produce in its `final/` directory:
- `final.mp4` — video with narration
- `final_with_sfx.mp4` — video with narration + Veo sound effects
- `final_images_only.mp4` — static images + narration (may be skipped if audio extraction fails)

## Known Issues

- Voice mode: if `start_time`/`end_time` are missing or zero, audio extraction falls back to silence. The timestamps from the transcript are required.
- Replicate image generation and Veo video generation may retry on rate limits — this is normal.
- `extract_audio_segment` uses AAC codec, so audio segments use `.m4a` extension (not `.mp3`).
