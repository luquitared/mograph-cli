#!/usr/bin/env python3
"""Deepgram transcription module for voice-to-script pipeline.

Transcribes uploaded audio files and extracts word-level timestamps
for intelligent script segmentation.
"""

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from deepgram import DeepgramClient


@dataclass
class Word:
    """A single word with timing information."""
    word: str
    start: float  # seconds
    end: float    # seconds
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
        }


@dataclass
class TranscriptSegment:
    """A paragraph/segment of the transcript with words and timing."""
    text: str
    start: float
    end: float
    words: List[Word]

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def word_count(self) -> int:
        return len(self.words)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "word_count": self.word_count,
            "words": [w.to_dict() for w in self.words],
        }


@dataclass
class TranscriptionResult:
    """Complete transcription with metadata."""
    full_text: str
    segments: List[TranscriptSegment]
    total_duration: float
    total_words: int
    average_wps: float  # words per second
    raw_response: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "full_text": self.full_text,
            "total_duration": self.total_duration,
            "total_words": self.total_words,
            "average_wps": self.average_wps,
            "segments": [s.to_dict() for s in self.segments],
        }

    def to_llm_context(self, detailed: bool = True) -> str:
        """Format transcript for LLM consumption - token efficient but rich.

        Args:
            detailed: If True, include word-level timestamps for precise segmentation

        Returns a structured text format with word timestamps that the LLM
        can use to intelligently segment the transcript into scenes.
        """
        lines = [
            "=== VOICE TRANSCRIPT ===",
            f"Total Duration: {self.total_duration:.1f}s | Words: {self.total_words} | Avg WPS: {self.average_wps:.2f}",
            "",
            "NOTE: This is an automated transcription - there may be minor errors.",
            "Use context clues to interpret unclear words.",
            "",
        ]

        all_words = []
        for seg in self.segments:
            all_words.extend(seg.words)

        if detailed and all_words:
            # Detailed mode: show every word with timestamp for precise scene boundaries
            lines.append("--- WORD-LEVEL TIMESTAMPS ---")
            lines.append("Format: [start_time - end_time] word")
            lines.append("")

            # Group into sentences for readability while showing all timestamps
            current_sentence = []
            sentence_start = all_words[0].start

            for i, word in enumerate(all_words):
                current_sentence.append(f"{word.word}")

                # End sentence on punctuation or long pause
                is_sentence_end = (
                    word.word.endswith('.') or
                    word.word.endswith('?') or
                    word.word.endswith('!') or
                    word.word.endswith(',')
                )
                is_long_pause = (i + 1 < len(all_words) and
                                all_words[i + 1].start - word.end > 0.4)

                if is_sentence_end or is_long_pause or i == len(all_words) - 1:
                    sentence_text = " ".join(current_sentence)
                    duration = word.end - sentence_start
                    lines.append(f"[{sentence_start:.2f}s - {word.end:.2f}s] ({duration:.1f}s) {sentence_text}")
                    current_sentence = []
                    if i + 1 < len(all_words):
                        sentence_start = all_words[i + 1].start

            lines.append("")
            lines.append("--- FULL WORD TIMING DATA ---")
            lines.append("(Use this to find precise cut points)")
            lines.append("")

            # Compact word timing: word@start-end
            word_timings = []
            for word in all_words:
                word_timings.append(f"{word.word}@{word.start:.2f}")

            # Output in groups of 10 for readability
            for i in range(0, len(word_timings), 10):
                chunk = word_timings[i:i+10]
                lines.append(" | ".join(chunk))

        else:
            # Simple mode: grouped by phrases
            lines.append("--- TIMESTAMPED TRANSCRIPT ---")
            lines.append("")
            current_line = []
            current_start = None

            for i, word in enumerate(all_words):
                if current_start is None:
                    current_start = word.start

                current_line.append(word.word)

                is_pause = (i + 1 < len(all_words) and
                           all_words[i + 1].start - word.end > 0.5)

                if len(current_line) >= 8 or is_pause or i == len(all_words) - 1:
                    line_text = " ".join(current_line)
                    lines.append(f"[{current_start:.1f}s] {line_text}")
                    current_line = []
                    current_start = None

        lines.append("")
        lines.append("--- END TRANSCRIPT ---")

        return "\n".join(lines)


def transcribe_audio(
    audio_path: Path,
    api_key: Optional[str] = None,
    language: str = "en",
    model: str = "nova-2",
    smart_format: bool = True,
    punctuate: bool = True,
    paragraphs: bool = True,
    diarize: bool = False,
) -> TranscriptionResult:
    """Transcribe an audio file using Deepgram.

    Args:
        audio_path: Path to audio file (mp3, wav, m4a, etc.)
        api_key: Deepgram API key (uses DEEPGRAM_API_KEY env var if not provided)
        language: Language code (default: "en")
        model: Deepgram model (default: "nova-2")
        smart_format: Apply smart formatting (numbers, dates, etc.)
        punctuate: Add punctuation
        paragraphs: Detect paragraphs
        diarize: Speaker diarization (if multiple speakers)

    Returns:
        TranscriptionResult with full text, segments, and word timestamps
    """
    api_key = api_key or os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY environment variable not set")

    client = DeepgramClient(api_key=api_key)

    # Read audio file as bytes
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    # Call the Deepgram API
    response = client.listen.v1.media.transcribe_file(
        request=audio_bytes,
        model=model,
        language=language,
        smart_format=smart_format,
        punctuate=punctuate,
        paragraphs=paragraphs,
        diarize=diarize,
        utterances=True,
    )

    # Convert response to dict for processing
    if hasattr(response, 'to_dict'):
        response_dict = response.to_dict()
    elif hasattr(response, 'model_dump'):
        response_dict = response.model_dump()
    else:
        # Fallback: manually extract data
        response_dict = {
            "results": {
                "channels": [{
                    "alternatives": [{
                        "transcript": getattr(response.results.channels[0].alternatives[0], 'transcript', ''),
                        "words": [
                            {
                                "punctuated_word": getattr(w, 'punctuated_word', getattr(w, 'word', '')),
                                "word": getattr(w, 'word', ''),
                                "start": getattr(w, 'start', 0),
                                "end": getattr(w, 'end', 0),
                                "confidence": getattr(w, 'confidence', 0),
                            }
                            for w in getattr(response.results.channels[0].alternatives[0], 'words', [])
                        ],
                        "paragraphs": getattr(response.results.channels[0].alternatives[0], 'paragraphs', None),
                    }]
                }]
            }
        }

    # Parse response
    results = response_dict.get("results", {})
    channels = results.get("channels", [])

    if not channels:
        raise ValueError("No transcription results found")

    alternatives = channels[0].get("alternatives", [])
    if not alternatives:
        raise ValueError("No transcription alternatives found")

    best_alt = alternatives[0]
    full_text = best_alt.get("transcript", "")

    # Extract word-level timestamps
    raw_words = best_alt.get("words", [])
    all_words: List[Word] = []

    for w in raw_words:
        all_words.append(Word(
            word=w.get("punctuated_word", w.get("word", "")),
            start=float(w.get("start", 0)),
            end=float(w.get("end", 0)),
            confidence=float(w.get("confidence", 0)),
        ))

    # Build segments from paragraphs or create single segment
    paragraphs_data = best_alt.get("paragraphs", {})
    if paragraphs_data and isinstance(paragraphs_data, dict):
        paragraphs_data = paragraphs_data.get("paragraphs", [])
    else:
        paragraphs_data = []

    segments: List[TranscriptSegment] = []

    if paragraphs_data:
        for para in paragraphs_data:
            para_words = []
            for sent in para.get("sentences", []):
                sent_start = sent.get("start", 0)
                sent_end = sent.get("end", 0)
                # Find words in this sentence time range
                for w in all_words:
                    if w.start >= sent_start and w.end <= sent_end + 0.1:
                        para_words.append(w)

            if para_words:
                segments.append(TranscriptSegment(
                    text=" ".join(w.word for w in para_words),
                    start=para_words[0].start,
                    end=para_words[-1].end,
                    words=para_words,
                ))
    else:
        # Single segment with all words
        if all_words:
            segments.append(TranscriptSegment(
                text=full_text,
                start=all_words[0].start,
                end=all_words[-1].end,
                words=all_words,
            ))

    # Calculate stats
    total_duration = all_words[-1].end if all_words else 0
    total_words = len(all_words)
    average_wps = total_words / total_duration if total_duration > 0 else 0

    return TranscriptionResult(
        full_text=full_text,
        segments=segments,
        total_duration=total_duration,
        total_words=total_words,
        average_wps=average_wps,
        raw_response=response_dict,
    )


def segment_for_pacing(
    transcript: TranscriptionResult,
    pacing: str,
) -> List[Dict[str, Any]]:
    """Segment transcript based on pacing option.

    Args:
        transcript: TranscriptionResult from transcribe_audio
        pacing: Pacing option:
            - "dual-4s": Two 4-second clips per scene (8s narration per scene)
            - "single-6s": One 6-second clip per scene (6s narration per scene)

    Returns:
        List of suggested scene segments with timing info
    """
    if pacing == "dual-4s":
        target_scene_duration = 8.0
        clips_per_scene = 2
        clip_duration = 4
    elif pacing == "single-6s":
        target_scene_duration = 6.0
        clips_per_scene = 1
        clip_duration = 6
    else:
        raise ValueError(f"Unknown pacing option: {pacing}")

    # Collect all words with timing
    all_words = []
    for seg in transcript.segments:
        all_words.extend(seg.words)

    if not all_words:
        return []

    # Segment based on target duration
    scenes = []
    current_scene_words = []
    current_scene_start = all_words[0].start

    for word in all_words:
        current_scene_words.append(word)
        current_duration = word.end - current_scene_start

        # Check if we've hit the target duration (with some tolerance)
        # Also check for natural pause points
        is_pause = len(current_scene_words) > 1 and (
            word.word.endswith('.') or
            word.word.endswith('?') or
            word.word.endswith('!')
        )

        if current_duration >= target_scene_duration * 0.85 and (is_pause or current_duration >= target_scene_duration):
            scenes.append({
                "text": " ".join(w.word for w in current_scene_words),
                "start": current_scene_start,
                "end": word.end,
                "duration": word.end - current_scene_start,
                "word_count": len(current_scene_words),
                "clips_per_scene": clips_per_scene,
                "clip_duration": clip_duration,
                "words": [w.to_dict() for w in current_scene_words],
            })
            current_scene_words = []
            current_scene_start = None

    # Handle remaining words
    if current_scene_words:
        scenes.append({
            "text": " ".join(w.word for w in current_scene_words),
            "start": current_scene_start or current_scene_words[0].start,
            "end": current_scene_words[-1].end,
            "duration": current_scene_words[-1].end - (current_scene_start or current_scene_words[0].start),
            "word_count": len(current_scene_words),
            "clips_per_scene": clips_per_scene,
            "clip_duration": clip_duration,
            "words": [w.to_dict() for w in current_scene_words],
        })

    return scenes


# --- CLI ---

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Transcribe audio using Deepgram and output word timestamps."
    )
    p.add_argument("audio_file", type=Path, help="Path to audio file")
    p.add_argument("--out", type=Path, help="Output JSON path (default: <audio>.transcript.json)")
    p.add_argument("--language", default="en", help="Language code (default: en)")
    p.add_argument("--model", default="nova-2", help="Deepgram model (default: nova-2)")
    p.add_argument("--pacing", choices=["dual-4s", "single-6s"],
                   help="Segment for pacing option")
    p.add_argument("--llm-format", action="store_true",
                   help="Also output LLM-friendly format to .llm.txt")
    return p


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if not args.audio_file.exists():
        raise SystemExit(f"Audio file not found: {args.audio_file}")

    print(f"Transcribing: {args.audio_file}")
    result = transcribe_audio(
        args.audio_file,
        language=args.language,
        model=args.model,
    )

    print(f"Duration: {result.total_duration:.1f}s")
    print(f"Words: {result.total_words}")
    print(f"Average WPS: {result.average_wps:.2f}")

    # Output path
    out_path = args.out or args.audio_file.with_suffix(".transcript.json")

    output_data = result.to_dict()

    # Add pacing segments if requested
    if args.pacing:
        output_data["pacing_segments"] = segment_for_pacing(result, args.pacing)
        print(f"Pacing ({args.pacing}): {len(output_data['pacing_segments'])} scenes")

    out_path.write_text(json.dumps(output_data, indent=2, ensure_ascii=False))
    print(f"Wrote: {out_path}")

    # Write LLM format if requested
    if args.llm_format:
        llm_path = args.audio_file.with_suffix(".llm.txt")
        llm_path.write_text(result.to_llm_context())
        print(f"Wrote LLM format: {llm_path}")


if __name__ == "__main__":
    main()
