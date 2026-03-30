#!/usr/bin/env python3
"""Convert ElevenLabs TTS timestamps to transcript format for scene generation.

This module parses ElevenLabs character-level timestamps and produces
a transcript format similar to Deepgram's output, enabling the TTS-first
pipeline mode where audio is generated upfront and scenes are designed
around actual speech timing.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TTSWord:
    """A single word with timing information from TTS."""
    word: str
    start: float  # seconds
    end: float    # seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "start": self.start,
            "end": self.end,
        }


@dataclass
class TTSTranscript:
    """Transcript derived from ElevenLabs TTS timestamps."""
    full_text: str
    words: List[TTSWord]
    total_duration: float
    total_words: int
    average_wps: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "full_text": self.full_text,
            "total_duration": self.total_duration,
            "total_words": self.total_words,
            "average_wps": self.average_wps,
            "words": [w.to_dict() for w in self.words],
        }

    def to_llm_context(self) -> str:
        """Format transcript for LLM consumption - matches voice mode format."""
        lines = [
            "=== TTS TRANSCRIPT (EXACT TIMING) ===",
            f"Total Duration: {self.total_duration:.2f}s | Words: {self.total_words} | Avg WPS: {self.average_wps:.2f}",
            "",
            "NOTE: These timestamps are from the actual TTS audio - they are EXACT.",
            "Use these precise timings to design optimal scene boundaries.",
            "",
        ]

        if self.words:
            lines.append("--- WORD-LEVEL TIMESTAMPS ---")
            lines.append("Format: [start_time - end_time] word")
            lines.append("")

            # Group into sentences for readability while showing all timestamps
            current_sentence = []
            sentence_start = self.words[0].start

            for i, word in enumerate(self.words):
                current_sentence.append(word.word)

                # End sentence on punctuation or long pause
                is_sentence_end = (
                    word.word.endswith('.') or
                    word.word.endswith('?') or
                    word.word.endswith('!') or
                    word.word.endswith(',')
                )
                is_long_pause = (i + 1 < len(self.words) and
                                self.words[i + 1].start - word.end > 0.3)

                if is_sentence_end or is_long_pause or i == len(self.words) - 1:
                    sentence_text = " ".join(current_sentence)
                    duration = word.end - sentence_start
                    lines.append(f"[{sentence_start:.2f}s - {word.end:.2f}s] ({duration:.2f}s) {sentence_text}")
                    current_sentence = []
                    if i + 1 < len(self.words):
                        sentence_start = self.words[i + 1].start

            lines.append("")
            lines.append("--- FULL WORD TIMING DATA ---")
            lines.append("(Use this to find precise cut points)")
            lines.append("")

            # Compact word timing: word@start-end
            word_timings = []
            for word in self.words:
                word_timings.append(f"{word.word}@{word.start:.2f}-{word.end:.2f}")

            # Output in groups of 8 for readability
            for i in range(0, len(word_timings), 8):
                chunk = word_timings[i:i+8]
                lines.append(" | ".join(chunk))

        lines.append("")
        lines.append("--- END TRANSCRIPT ---")

        return "\n".join(lines)


def parse_elevenlabs_alignment(
    text: str,
    alignment: Dict[str, Any],
) -> List[TTSWord]:
    """Parse ElevenLabs alignment into word-level timing.

    Handles two formats:
    1. Old TTS format with separate arrays:
        - characters: list of single characters
        - character_start_times_seconds: list of floats
        - character_end_times_seconds: list of floats

    2. New Forced Alignment format with objects:
        - words: list of {text, start, end, loss}
        - characters: list of {text, start, end}

    Args:
        text: The original text that was synthesized
        alignment: The alignment dict from ElevenLabs

    Returns:
        List of TTSWord objects with word-level timing
    """
    # Check if this is the new Forced Alignment format (has words array with objects)
    words_data = alignment.get("words", [])
    if words_data and isinstance(words_data[0], dict) and "text" in words_data[0]:
        # New Forced Alignment format - words already parsed!
        words: List[TTSWord] = []
        for w in words_data:
            word_text = w.get("text", "").strip()
            # Skip whitespace-only entries
            if word_text and word_text not in (" ", "\n", "\t"):
                words.append(TTSWord(
                    word=word_text,
                    start=w.get("start", 0),
                    end=w.get("end", 0),
                ))
        return words

    # Old TTS format with separate character arrays
    characters = alignment.get("characters", [])
    start_times = alignment.get("character_start_times_seconds", [])
    end_times = alignment.get("character_end_times_seconds", [])

    # Also check if characters is in new format (list of dicts)
    if characters and isinstance(characters[0], dict):
        # Characters are objects with text/start/end - reconstruct words
        words = []
        current_word_chars: List[str] = []
        word_start: Optional[float] = None
        word_end: float = 0.0

        for char_obj in characters:
            char = char_obj.get("text", "")
            start = char_obj.get("start", 0)
            end = char_obj.get("end", 0)

            if char == " ":
                if current_word_chars:
                    word_text = "".join(current_word_chars).strip()
                    if word_text and word_start is not None:
                        words.append(TTSWord(word=word_text, start=word_start, end=word_end))
                    current_word_chars = []
                    word_start = None
            else:
                if word_start is None:
                    word_start = start
                current_word_chars.append(char)
                word_end = end

        # Handle last word
        if current_word_chars:
            word_text = "".join(current_word_chars).strip()
            if word_text and word_start is not None:
                words.append(TTSWord(word=word_text, start=word_start, end=word_end))

        return words

    # Original format with separate arrays
    if not characters or not start_times or not end_times:
        return []

    # Ensure arrays are same length
    min_len = min(len(characters), len(start_times), len(end_times))
    characters = characters[:min_len]
    start_times = start_times[:min_len]
    end_times = end_times[:min_len]

    words = []
    current_word_chars: List[str] = []
    word_start: Optional[float] = None
    word_end: float = 0.0

    for i, (char, start, end) in enumerate(zip(characters, start_times, end_times)):
        if char == " ":
            # Space ends the current word
            if current_word_chars:
                word_text = "".join(current_word_chars).strip()
                if word_text and word_start is not None:
                    words.append(TTSWord(
                        word=word_text,
                        start=word_start,
                        end=word_end,
                    ))
                current_word_chars = []
                word_start = None
        else:
            # Part of a word
            if word_start is None:
                word_start = start
            current_word_chars.append(char)
            word_end = end

    # Handle last word if no trailing space
    if current_word_chars:
        word_text = "".join(current_word_chars).strip()
        if word_text and word_start is not None:
            words.append(TTSWord(
                word=word_text,
                start=word_start,
                end=word_end,
            ))

    return words


def create_tts_transcript(
    text: str,
    timestamps_data: Dict[str, Any],
    audio_duration: Optional[float] = None,
) -> TTSTranscript:
    """Create a TTSTranscript from ElevenLabs timestamps JSON.

    Args:
        text: The original text (or use timestamps_data["text"])
        timestamps_data: The full timestamps JSON from ElevenLabs
        audio_duration: Optional override for total duration

    Returns:
        TTSTranscript with word-level timing
    """
    # Get text from timestamps if not provided
    if not text:
        text = timestamps_data.get("text", "")

    # Try alignment first, fall back to normalized_alignment
    alignment = timestamps_data.get("alignment") or timestamps_data.get("normalized_alignment")
    if not alignment:
        raise ValueError("No alignment data found in timestamps")

    words = parse_elevenlabs_alignment(text, alignment)

    # Calculate duration from last word if not provided
    if audio_duration is None and words:
        audio_duration = words[-1].end
    elif audio_duration is None:
        audio_duration = 0.0

    total_words = len(words)
    average_wps = total_words / audio_duration if audio_duration > 0 else 0.0

    return TTSTranscript(
        full_text=text,
        words=words,
        total_duration=audio_duration,
        total_words=total_words,
        average_wps=average_wps,
    )


def create_combined_transcript(
    scene_narrations: List[str],
    timestamps_path: Path,
    audio_duration: Optional[float] = None,
) -> TTSTranscript:
    """Create a TTSTranscript from a combined TTS timestamps file.

    Args:
        scene_narrations: List of scene narrator texts (for reference)
        timestamps_path: Path to the combined.timestamps.json file
        audio_duration: Optional override for total duration

    Returns:
        TTSTranscript with word-level timing for the entire narration
    """
    timestamps_data = json.loads(timestamps_path.read_text())
    full_text = " ".join(scene_narrations)
    return create_tts_transcript(full_text, timestamps_data, audio_duration)


# --- CLI for testing ---

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Parse ElevenLabs timestamps to transcript format"
    )
    parser.add_argument("timestamps_json", type=Path, help="Path to .timestamps.json file")
    parser.add_argument("--audio-duration", type=float, help="Override audio duration")
    parser.add_argument("--llm-format", action="store_true", help="Output LLM-friendly format")
    args = parser.parse_args()

    if not args.timestamps_json.exists():
        raise SystemExit(f"File not found: {args.timestamps_json}")

    timestamps_data = json.loads(args.timestamps_json.read_text())
    text = timestamps_data.get("text", "")

    transcript = create_tts_transcript(text, timestamps_data, args.audio_duration)

    print(f"Duration: {transcript.total_duration:.2f}s")
    print(f"Words: {transcript.total_words}")
    print(f"Average WPS: {transcript.average_wps:.2f}")
    print()

    if args.llm_format:
        print(transcript.to_llm_context())
    else:
        print(json.dumps(transcript.to_dict(), indent=2))


if __name__ == "__main__":
    main()
