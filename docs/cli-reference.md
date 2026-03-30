# CLI Reference

## Pipeline Arguments

```bash
pipeline.py:
  # Input options
  --script-file PATH         # Script file (with scenes: script mode)
  --main-ref PATH            # Aspect ratio reference (blank image)
  --reference-image PATH     # Style reference images

  # Stage control
  --stage {images,videos,final}  # Highest stage to run
  --resume-dir PATH          # Resume from existing run

  # Mode control
  --tts-only                 # Generate TTS + timestamps, then stop
  --target-seconds N         # Target video duration for narration generation (default: 30)

  # Models
  --image-model MODEL        # Image model (default: gemini-2.5-flash-image-preview)
  --video-model {quality,fast,kling}  # Video model (default: fast)

  # Video settings
  --video-seconds SEC       # Video duration per scene (default: 6)
  --video-resolution RES    # Resolution (default: 720p)
  --video-concurrency N     # Concurrent videos (default: 8)
  --video-buffer-ms MS      # Add/subtract milliseconds from video duration (default: 0)
  --timing-mode {audio-match,video-match}  # How to reconcile audio/video length (default: audio-match)
  --start-frame-mode {transition,reference,sequential,animate}  # First frame mode (default: animate)

  # Audio settings (Gemini TTS)
  --voice NAME               # Gemini voice name (default: Kore)
  --tts-model MODEL          # Gemini TTS model (default: gemini-2.5-flash-preview-tts)
  --tts-concurrency N        # Concurrent TTS requests (default: 5)
  --veo-audio-volume FLOAT   # Veo SFX volume (0.0-1.0, default: 0.3)
  --list-voices              # List available Gemini voices and exit

  # Performance
  --concurrency N            # Concurrent images (default: 4)
  --max-images N             # Max images to generate

  # Options
  --alternatives             # Generate all visual variations
  --enable-text-verification # Enable quality verification (disabled by default)
  --dry-run                  # Test without API calls
  --mock                     # Use mock fixtures instead of Replicate API
  --output-root DIR          # Output directory (default: runs)
  --final-name FILE          # Final video name (default: final.mp4)

  # Special modes
  --voice-file PATH          # Voice mode: use your own voice recording
  --style-notes TEXT         # Style notes for voice mode
```

## Staged Execution

```bash
# Stage 1: Generate images only
python pipeline.py --script-file my-script.json --stage images

# Stage 2: Generate videos (resume from stage 1)
python pipeline.py --resume-dir runs/my-video-20250122-120000 --stage videos

# Stage 3: Add narration and assemble
python pipeline.py --resume-dir runs/my-video-20250122-120000 --stage final
```

## Resume Behavior

- **Script Preservation**: If `script.json` exists in the run directory, it is reused (allows manual edits)
- **Incremental Video Retry**: Existing videos are skipped; only missing ones are generated
- **Re-running Stages**: Edit `run_config.json` and remove the stage from `completed_stages` array
- **Image Fallback**: If Veo fails for a clip, the static image is used as a stand-in (saved to `videos_fallback/`)

## Video Models

| Model            | CLI Flag                | Resolution              | Duration Options | Best For                      |
| ---------------- | ----------------------- | ----------------------- | ---------------- | ----------------------------- |
| Veo 3.1          | `--video-model quality` | Up to 1080p             | 4, 6, 8s         | Higher quality output         |
| Veo 3.1 Fast     | `--video-model fast`    | Up to 720p              | 4, 6, 8s         | Faster generation             |
| Kling v3 Omni    | `--video-model kling`   | 720p (standard) / 1080p (pro) | 3–15s      | Flexible duration, native audio |

## Mock Mode (Testing)

```bash
python pipeline.py --script-file my-script.json --mock --stage final
```

Mocked: Image generation (copies `tests/fixtures/mock_image.png`), video generation (copies `tests/fixtures/mock_video.mp4`).
Still runs: Gemini TTS (real narration), FFmpeg assembly (real processing).

## Output Structure

```
runs/<run-name>/
├── script.json, batch.json, run_config.json
├── images/          # Generated images per scene
├── videos/          # Generated video clips
├── audio/           # TTS narration per scene (.mp3 + .timestamps.json)
└── final/
    ├── final.mp4              # Narration only
    ├── final_with_sfx.mp4     # Narration + Veo sound effects (30% volume)
    └── final_images_only.mp4  # Static images + narration (no animation)
```
