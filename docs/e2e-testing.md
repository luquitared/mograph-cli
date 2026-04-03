# End-to-End Testing

## Why E2E tests with real generation?

Mock mode (`--mock`) is fast and free, but it hides entire categories of bugs:

| What mock mode hides | Why it matters |
|---|---|
| **Retry & error handling** | Rate limits, content moderation rejections, and transient API failures never trigger |
| **Timing & alignment** | Mock TTS returns evenly-spaced fake timestamps; real speech has variable cadence |
| **Media format variance** | Every scene gets the same static fixture file — resolution mismatches never surface |
| **API contract drift** | Model updates, new error codes, or changed output formats are invisible until you hit the real API |
| **Prompt quality** | The only way to know if your prompts produce good visuals is to actually generate them |

## Running E2E tests

### Single timeline

```bash
python pipeline.py --timeline-file tests/e2e_scripts/01_text_heavy_infographic.json --stage final
```

### Mock mode (pipeline logic only, no credits)

```bash
python pipeline.py --mock --timeline-file tests/e2e_scripts/04_multi_clip_scene.json --stage final
```

## Tracking generations

After each run, use the tracking script:

```bash
python tests/e2e_log.py [--runs-dir runs]
```

This scans all run directories and produces `tests/e2e_generation_log.jsonl`.

## When to run E2E tests

| Trigger | What to run |
|---|---|
| Before a release or deploy | All test timelines, full pipeline (`--stage final`) |
| After changing image/video generation code | Relevant timelines only |
| After updating prompts or prompt templates | All timelines to check generation quality |
| After upgrading a model version | All timelines — model behavior changes are unpredictable |

## Cost estimate

Each 2-scene timeline costs roughly $0.30–$0.80 depending on video model and duration settings. This is cheap insurance against shipping broken pipelines or degraded prompt quality.
