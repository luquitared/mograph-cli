# pipeline/

Script-to-batch conversion. Converts structured video scripts into batch image generation format.

## Files

- `__init__.py` — Package init
- `script_to_batch.py` — Converts script JSON to batch image generation input format for `generation/batch_img.py`

## Key Interfaces

**script_to_batch.py:**
- `convert_script_to_batch(script_path, output_dir, ...)` — Converts script JSON to batch format with `requests[]` array and `visual_map[]`

**Script JSON format:**
```json
{
  "script_title": "...",
  "subject": "...",
  "brand_name": "...",
  "scenes": [{
    "scene_number": 1,
    "narrator": "spoken text",
    "visuals": [{"concept_name": "...", "image_prompt": "...", "animation_prompt": "...", "duration": 6}],
    "start_time": 0.0, "end_time": 6.0
  }]
}
```

Timing fields (`start_time`, `end_time`, visual `duration`) are present in voice and TTS-only modes.

## Dependencies

- **Imports from**: `shared.common` (slugify_identifier)
- **Imported by**: `pipeline.py`
