# Timeline Format Documentation

Documentation for the timeline-based video project format. Organized in layers from quick-start to deep reference.

## Layer 1: Examples (copy and modify)

Start here. Each example is a valid, runnable timeline JSON file with inline `_comment` fields explaining key decisions.

- [`examples/simple-explainer.json`](examples/simple-explainer.json) — Basic TTS narration + video clips
- [`examples/voice-mode.json`](examples/voice-mode.json) — Pre-recorded audio with file sources
- [`examples/exploration.json`](examples/exploration.json) — Prompt variant exploration with candidates
- [`examples/sequential.json`](examples/sequential.json) — Last-frame chaining for visual continuity
- [`examples/multi-track.json`](examples/multi-track.json) — Multiple audio tracks with volume mixing

## Layer 2: Format Reference (authoritative field docs)

Complete field-by-field schema documentation covering every field, type, default, and constraint.

- [`format-reference.md`](format-reference.md)
- [`timeline.schema.json`](timeline.schema.json) — JSON Schema for programmatic validation

## Layer 3: Model Reference (per-model details)

Parameters, constraints, cost considerations, and when to use each generation model.

- [`models.md`](models.md)

## Layer 4: Patterns (complex workflow recipes)

Advanced techniques: cross-referencing, exploration workflows, timing strategies, audio layering.

- [`patterns.md`](patterns.md)
