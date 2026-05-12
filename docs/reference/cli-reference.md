# CLI Reference

## Pipeline Arguments

```bash
pipeline.py:
  # Input (required)
  --timeline-file PATH       # Path to timeline JSON file

  # Stage control
  --stage {images,videos,final}  # Highest stage to run (default: final)
  --resume-dir PATH          # Resume from existing run

  # Audio settings (Gemini TTS)
  --voice NAME               # Gemini voice name (default: Kore)
  --tts-model MODEL          # Gemini TTS model (default: gemini-3.1-flash-tts-preview)
  --tts-concurrency N        # Concurrent TTS requests (default: 5)
  --list-voices              # List available Gemini voices and exit

  # Video settings
  --video-concurrency N      # Concurrent video generations (default: 8)

  # Options
  --dry-run                  # Show execution plan without running
  --mock                     # Use mock fixtures instead of API calls
  --output-root DIR          # Output directory (default: runs)
```

## Staged Execution

```bash
# Stage 1: Generate images only
python pipeline.py --timeline-file my-timeline.json --stage images

# Stage 2: Generate videos (resume from stage 1)
python pipeline.py --timeline-file my-timeline.json --resume-dir runs/my-video-20250122-120000 --stage videos

# Stage 3: Add narration and assemble
python pipeline.py --timeline-file my-timeline.json --resume-dir runs/my-video-20250122-120000 --stage final
```

## Resume Behavior

- **Incremental**: Completed stages are skipped on resume
- **Re-running Stages**: The timeline executor tracks completed nodes in the DAG

## Mock Mode (Testing)

```bash
python pipeline.py --timeline-file my-timeline.json --mock --stage final
```

Mocked: Image generation, video generation (uses test fixtures).
Still runs: Gemini TTS (real narration), FFmpeg assembly (real processing).

## Output Structure

```
runs/<run-name>/
├── images/          # Generated images
├── videos/          # Generated video clips
├── audio/           # TTS narration (.mp3)
└── final/
    ├── final.mp4              # Narration only
    └── final_with_sfx.mp4     # Narration + sound effects
```
