"""Cost constants for generation APIs.

Seedance 2.0 pricing (per second of output video):
  video_in (has reference_videos):
    480p: $0.13/s
    720p: $0.29/s
  non_video_in (text/image only):
    480p: $0.07/s
    720p: $0.17/s

Seedance 2.0 Fast pricing (per second of output video):
  video_in:
    480p: $0.11/s
    720p: $0.22/s
  non_video_in:
    480p: $0.06/s
    720p: $0.13/s

Veo 3.1 Lite: ~$0.15/s at 720p
"""

IMAGE_COST_USD = 0.15  # nano-banana-pro per image

# Seedance 2.0 pricing tiers
SEEDANCE_COST_PER_SEC = {
    ("non_video_in", "480p"): 0.07,
    ("non_video_in", "720p"): 0.17,
    ("video_in", "480p"): 0.13,
    ("video_in", "720p"): 0.29,
}

# Seedance 2.0 Fast pricing tiers (14-24% cheaper)
SEEDANCE_FAST_COST_PER_SEC = {
    ("non_video_in", "480p"): 0.06,
    ("non_video_in", "720p"): 0.13,
    ("video_in", "480p"): 0.11,
    ("video_in", "720p"): 0.22,
}

# Veo 3.1 Lite
VEO_LITE_COST_PER_SEC = 0.15

# Legacy alias
VIDEO_SECOND_COST_USD = 0.06  # cheapest option: seedance-fast non_video_in 480p
TTS_COST_USD = 0.0  # Gemini TTS currently free


def estimate_seedance_cost(duration_sec: int, resolution: str = "480p",
                           has_video_refs: bool = False, fast: bool = True) -> float:
    """Estimate cost for a Seedance generation."""
    variant = "video_in" if has_video_refs else "non_video_in"
    table = SEEDANCE_FAST_COST_PER_SEC if fast else SEEDANCE_COST_PER_SEC
    rate = table.get((variant, resolution), 0.06)
    return duration_sec * rate
