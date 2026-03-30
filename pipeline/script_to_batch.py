#!/usr/bin/env python3
"""Convert script output to batch_img input."""

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from shared.common import slugify_identifier


VisualFilter = Callable[[Dict[str, Any], Dict[str, Any], int], bool]


def _normalize_media_path(path: str) -> str:
    """Trim leading images/ for downstream consumers while keeping custom paths."""
    if not path:
        return path
    prefix = "assets/images/"
    if path.startswith(prefix):
        trimmed = path[len(prefix):]
        if Path(trimmed).exists():
            return trimmed
        return path
    return path


def convert_script_to_batch(
    script_path,
    output_dir,
    blank_image_path="assets/images/main-ref-images/blank_white_9x16.png",
    visual_filter: Optional[VisualFilter] = None,
    aspect_ratio: Optional[str] = None,
    reference_images: Optional[List[str]] = None,
):
    """Convert a script JSON to batch image generation format.

    Args:
        script_path: Path to the script JSON file
        output_dir: Directory for generated images
        blank_image_path: Path to blank reference image for aspect ratio
        visual_filter: Optional filter function for visuals
        aspect_ratio: Optional aspect ratio override (e.g., "16:9", "9:16")
        reference_images: Optional list of reference image paths. If provided,
            these override the script's reference_images. Use this to pass
            resolved absolute paths (e.g., from CLI --reference-image args or
            downloaded files on Cloud Run).
    """
    with open(script_path, "r") as f:
        script = json.load(f)

    batch_input = {
        "default_messages": [],
        "requests": []
    }

    # Use provided reference_images if given, otherwise fall back to script
    ref_images = reference_images if reference_images is not None else (script.get("reference_images") or [])
    normalized_references: List[str] = []
    for ref_path in ref_images:
        normalized_path = _normalize_media_path(ref_path)
        if normalized_path:
            normalized_references.append(normalized_path)

    normalized_blank_path = _normalize_media_path(blank_image_path)

    # Create requests for each visual in each scene
    visual_map: List[Dict[str, Any]] = []

    for scene in script.get("scenes", []):
        scene_num = scene.get("scene_number")
        scene_type = scene.get("scene_type", "scene")
        scene_label = slugify_identifier(str(scene_type), "scene")

        for visual_idx, visual in enumerate(scene.get("visuals", [])):
            if visual_filter and not visual_filter(scene, visual, visual_idx):
                continue
            prompt = visual.get("image_prompt", "")
            concept_name = visual.get("concept_name", "visual")
            concept_label = slugify_identifier(concept_name, "visual")
            filename = f"scene{scene_num}_{scene_label}_{concept_label}.png"

            parts = [
                f"{prompt}",
            ]
            prompt_text = "\n".join(p for p in parts if p).strip()

            request = {
                "prompt": prompt_text,
                "image_paths": [normalized_blank_path] if normalized_blank_path else [],
                "reference_images": normalized_references,
                "filename": filename,
                "output_dir": output_dir
            }

            # Add aspect ratio config if provided
            if aspect_ratio:
                request["config"] = {"aspect_ratio": aspect_ratio}
            batch_input["requests"].append(request)

            visual_map.append(
                {
                    "scene_number": scene_num,
                    "visual_index": visual_idx,
                    "filename": filename,
                    "type": visual.get("type"),
                }
            )

    batch_input["visual_map"] = visual_map

    return batch_input

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python script_to_batch.py <script_json> <output_dir> [blank_image_path]")
        sys.exit(1)
    
    script_path = sys.argv[1]
    output_dir = sys.argv[2]
    blank_image = sys.argv[3] if len(sys.argv) > 3 else "assets/images/main-ref-images/blank_white_9x16.png"
    
    batch = convert_script_to_batch(script_path, output_dir, blank_image)
    
    # Save batch input
    script_name = Path(script_path).stem
    batch_path = Path(script_path).parent / f"{script_name}_batch.json"
    
    with open(batch_path, 'w') as f:
        json.dump(batch, f, indent=2)
    
    print(f"✅ Batch input saved to: {batch_path}")
