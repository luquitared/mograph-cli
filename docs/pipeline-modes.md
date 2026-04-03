# Pipeline Modes

## Timeline Format

The pipeline uses a timeline JSON format for all video generation. A timeline defines tracks with clips, where each clip specifies its media sources (images, video, TTS audio).

```bash
python pipeline.py --timeline-file my-timeline.json --stage final
```

## Staged Execution

| Stage | What happens |
|-------|-------------|
| `images` | Generate images from clip prompts |
| `videos` | Generate images + video clips |
| `final` | Full pipeline: images, videos, TTS, and final assembly |

## Exploration Mode

When a timeline uses `explore` settings, the pipeline generates multiple candidates and pauses for selection:

```bash
# Initial run generates candidates and pauses
python pipeline.py --timeline-file my-timeline.json --stage final

# After selecting candidates, resume
python pipeline.py --timeline-file my-timeline.json --resume-dir runs/<run-dir> --stage final
```

## Dry Run

Preview the execution plan without running:

```bash
python pipeline.py --timeline-file my-timeline.json --dry-run
```
