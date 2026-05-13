# Stick-figure explainer

Generate short narrated explainer videos in a minimal hand-drawn stick-figure style — black outlines on grey textured paper, AI-narrated, about 40–60 seconds long. Good for educational content where a concrete visual metaphor carries the explanation: how things work, why mechanisms behave the way they do, what's actually happening inside a process you usually just hear about.

## What you can make with it

This recipe is built for topics with namable parts and small visual gags — props, labels, contained mechanisms. Examples it does well:

- **How a thing works** — a thermos, DNS resolution, refrigeration, an internal combustion engine, the immune response, a pendulum clock
- **Why a mechanism behaves how it does** — why ice floats, why the sky is blue, why airfoils generate lift, why compounding interest accelerates
- **A walkthrough of a flow** — how a transaction settles, how a request hits an API gateway, how a vaccine trains a B cell
- **Concept primers** — what stablecoins are, what a CDN does, what a market maker actually does in the middle of a trade

It's not the right fit for talking-head presenters, cinematic or photoreal styles, recurring named characters, or topics where the visual carries no metaphorical weight (purely numerical / abstract math).

## What you customize

- **Your topic and script** — an 8-line narration (≤30 words per line; 4–15s when spoken) drives the whole video. Write it once; the workflow handles per-beat visuals and timing
- **Length** — 6 beats lands at ~30 seconds, 8 beats at ~50 seconds, 12 beats at ~70 seconds. Anything past a minute usually wants splitting
- **Narration voice** — Kore (casual, friendly) is the default; swap for any Gemini TTS voice if you want a different energy (see [`docs/reference/tts-voices.md`](../../reference/tts-voices.md))
- **Accent colors** — one or two per beat. Red for danger or loss, green for stability or gain, gold for value, blue for cool or calm. Mention them in your prompts and they'll show up consistently
- **Composition cues** — single-subject scenes for emphasis, two-panel splits for compare/contrast, labeled props and signs for anything with a name that matters

## What stays consistent so you can focus on the topic

Multi-clip AI video usually fights you on three things — visual style drift between clips, narration getting cut off or rushed, and Seedance producing over-cluttered scenes. The recipe pins all three:

- **Look stays the same across every beat.** A `prompt_prefix` on both image and video defaults binds black-outline stick figures on grey paper to every clip the pipeline generates. You don't have to restate the style in every prompt.
- **Narration and visuals stay in sync.** Each video clip uses `fit_to` to time-stretch itself to the actual TTS duration of its narration line — no clipped audio, no leftover dead frames at the end
- **Compositions stay clean.** A "One X" prompt convention (`One stick figure sits at one desk...`) keeps Seedance from cramming three characters into a frame
- **Narration audio doesn't fight Seedance audio.** Seedance's built-in audio generation is disabled — your TTS narration is the soundtrack, full stop

## Use it

Pull the recipe into a local checkout of [mograph-cli](https://github.com/luquitared/mograph-cli):

```
mograf workflow pull stick-figure-explainer
```

You get:

- `README.md` — this page
- `CLAUDE.md` / `AGENTS.md` — instructions for AI agents authoring new timelines in this style
- `examples/how-a-thermos-works.json` — the canonical worked example timeline
- `examples/how-a-thermos-works.mp4` — what that renders to (the video on this page)

Then either:

- **Edit the example timeline** with your own script and scene descriptions and run `python scripts/run.py examples/how-a-thermos-works.json --stage final`
- **Or hand it to an AI coding agent** (Claude Code, Codex, Cursor) — the `CLAUDE.md` / `AGENTS.md` tell it everything it needs to author a new timeline in this style from a topic you describe

## Cost and timing

About 3–8 minutes per render on a warm machine. Roughly $1–3 per video at current model prices — most of it goes to Seedance for the 8 video clips. Iterating on stills only (after you like the script) is cheap; iterating on motion alone is also cheap. See the staged-rendering docs in [narration-explainer](../narration-explainer/README.md) for how to rerun individual stages without redoing the whole pipeline.

## Built on

This is a style specialization of the [narration-explainer](../narration-explainer/README.md) workflow — the underlying two-track shape, timeline format, and staged rendering live there.
