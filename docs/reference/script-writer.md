# Script Writer — rules for engaging dialogue

Agent-facing guide for writing dialogue that lands with personality, not a robotic news-anchor monotone. Applies any time a clip's audio is driven by Gemini 3.1 Flash TTS — most notably the `voice-via-audio-ref/` + `news-video/` combined pattern where the Gemini WAV is the *exact* spoken dialogue and is fed to Seedance as `reference_audios`.

## Principle: bracket cues, in two places

`[ ]` brackets are how you steer expressivity in this pipeline. They live in two layers, and both matter:

1. **Gemini TTS text (highest leverage).** Gemini 3.1 Flash TTS supports 200+ inline `[tag]` audio tags including custom descriptors like `[like a cartoon dog]`. The tags actually change how the line is read. The resulting WAV IS the dialogue Seedance lip-syncs to — so if the read is flat here, the final clip is flat there. Fix it at the source.
2. **Seedance prompt.** Bracket cues describing the speaker's emotional state and micro-actions (e.g. `[wry smirk]`, `[mock-pity tilt]`) align the visual performance with the audio. Without them, Seedance defaults to a neutral talking-head loop.

Skip the brackets and you get the failure mode we shipped first: a polished anchor reading the words correctly with zero personality, eyebrows locked.

## Layer 1 — Gemini TTS text

Drop bracket tags directly inside the `text=` string passed to `GeminiTTS().synthesize_to_file`. Tags affect the surrounding clause, not the whole utterance, so place them where the shift happens.

```python
text = (
    "[dry deadpan] Tonight's lead story: a Brooklyn bodega has officially "
    "declared independence. [beat] [bemused] Officials are... [tiny scoff] "
    "baffled."
)
```

Common tag shapes that work:
- **Emotion**: `[deadpan]`, `[bright]`, `[earnest]`, `[exasperated]`, `[mock-pity]`, `[sincere]`, `[skeptical]`, `[smug]`, `[dry]`, `[bemused]`
- **Vocalizations**: `[laughs]`, `[scoffs]`, `[chuckles]`, `[sighs]`, `[gasps]`, `[clears throat]`
- **Delivery**: `[whispers]`, `[stage whisper]`, `[rushed]`, `[drawn out]`, `[clipped]`, `[singsong]`
- **Pauses**: `[beat]`, `[long beat]`, `[pause]`
- **Custom descriptors** (Gemini 3.1 supports free-form): `[like a tired sportscaster]`, `[as if confiding a secret]`, `[trailing off]`

You don't need to memorize a closed list — Gemini interprets reasonable bracket prose. Lean into specifics: `[bemused half-smile in the voice]` is more useful than `[happy]`.

The `voice_prompt` argument (the "Director's Notes") complements but doesn't replace inline tags. Use it for overall delivery character ("polished anchor, dry"); use inline tags for the per-clause variation that makes it not robotic.

## Layer 2 — Seedance prompt

Mirror the audio's emotional beats with bracket cues for the face/body. Put the EXACT spoken line in single quotes; put the visual cues outside the quotes as brief bracketed prose.

```
Maya [dry smirk] turns to camera and delivers exactly: 'Tonight's lead
story: a Brooklyn bodega has officially declared independence. [beat]
Officials are... baffled.' [one slow eyebrow raise on 'baffled'].
```

The dialogue text inside the quotes can carry the *same* bracket cues you used in the TTS — Seedance does pick up on `[beat]` / `[scoffs]` as performance hints, so duplicating them inside the quoted line reinforces the lip-sync timing.

Visual bracket cues should be:
- **Micro-actions, not blocking**: `[wry smirk]`, `[half-step lean in]`, `[head tilt]`, `[breath in before speaking]`
- **One per emotional shift**, not three per second
- **Aligned with the audio tag**: if the WAV has `[scoffs]`, the prompt should have `[short scoff]` on the same word

## The rules

1. **No timecoded blocking.** `[0.0s-2.0s] HOLD... [2.0s-5.5s] X turns...` produces stilted, beat-by-beat acting. Write flowing emotion-led prose with `[bracket]` cues for performance moments. (See `feedback_gemini_audio_is_the_dialogue` in memory.)
2. **One speaking character per clip, tight framing.** Two-shots where one character speaks while another silently reacts have given visibly worse results — the model splits attention. Cut between solo shots if you need a two-character feel.
3. **Tight duration buffer.** `duration = clamp(ceil(audio_seconds) + 1.5..2s, 4, 15)`. Looser buffers (+4s) seem to encourage drift and robotic in-betweens.
4. **Single emotional arc per clip.** Pick one core feeling + one shift. "Dry → bemused" works. "Dry → bemused → outraged → resigned" does not, in 8–15 seconds.
5. **EXACT line in single quotes.** Seedance lip-syncs to the quoted text. Anything else around it is direction.
6. **Bracket cues, not adjectives in prose.** `[dry chuckle]` and "with a dry chuckle" land differently — brackets get treated as performance markers; prose gets treated as description and is more likely to be ignored.
7. **Specific > generic.** `[like a tired sportscaster]` beats `[tired]`. `[bemused half-smile in the voice]` beats `[amused]`.
8. **Don't pass a `reference_audios` voice for a silent character.** Even in solo-character clips, only the speaker's WAV goes in `reference_audios`. Otherwise Seedance may try to make the silent one speak. (See `feedback_seedance_audio_strategies`.)

## Before / after — Maya bodega line

**Before** (flat, robotic in testing):

TTS text:
```
Tonight's lead story: a Brooklyn bodega has officially declared independence. Officials are baffled.
```

Seedance prompt:
```
Maya turns to camera with a dramatic deadpan smirk and delivers exactly: 'Tonight's lead story: a Brooklyn bodega has officially declared independence. Officials are baffled.' One dramatic eyebrow raise on 'baffled'. Trip reacts visibly in a funny way to her. Trip slowly turns to Maya with a confused open-mouthed expression, no words.
```

**After** (bracket-cued):

TTS text:
```
[dry deadpan] Tonight's lead story: [tiny pause] a Brooklyn bodega has officially declared independence. [beat] [bemused, almost amused] Officials are... [trailing off] baffled.
```

Seedance prompt (solo framing, no silent reactor):
```
Maya at the news desk, [dry] turns to camera with a [slow wry smirk] and delivers exactly: '[dry deadpan] Tonight's lead story: a Brooklyn bodega has officially declared independence. [beat] [bemused] Officials are... baffled.' [one slow eyebrow raise on 'baffled', a half-suppressed exhale at the end].
```

The "after" puts the bracket cues in both layers, drops the silent reactor, and lets the cadence breathe instead of marching beat-to-beat.

## When to break the rules

- **Pure narration / b-roll voiceover** — no on-screen speaker, so layer 2 (Seedance visual cues) is irrelevant. Just write expressive TTS text with bracket tags and play it over generated b-roll.
- **Pre-recorded voice** — if the user is shipping their own WAV, you can't control delivery, only the visual prompt. Lean into layer 2.
- **Music video / format-rip workflows** — different beat structures govern; defer to those workflows' own CLAUDE.md.

## See also

- [`tts-voices.md`](tts-voices.md) — Gemini voice catalog
- [`../workflows/voice-via-audio-ref/CLAUDE.md`](../workflows/voice-via-audio-ref/CLAUDE.md) — the underlying pattern
- [`../workflows/news-video/CLAUDE.md`](../workflows/news-video/CLAUDE.md) — the cast/composite pattern that combines with this
