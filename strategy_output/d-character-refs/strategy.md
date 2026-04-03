# Strategy D: Character & Scene Reference Sheets

## Approach
Two-phase pipeline. First, generate dedicated anime character portraits and a scene establishing shot as standalone reference images. Then use those references to guide consistent video generation across all clips.

## Why this strategy
- **Character consistency**: The biggest risk with AI video is character drift — the King might look different in clip 1 vs clip 3. By generating a locked-in anime character reference first, every video frame is guided by the same design.
- **Scene consistency**: A dedicated throne room reference ensures the environment stays visually coherent.
- **Iterative refinement**: Phase 1 generates references with `candidates` for each character, so you can select the best anime design before committing to video generation. Bad reference → bad everything, so this step is worth getting right.
- **Reusable assets**: The generated character/scene refs live in `refs/` and can be reused across future timelines or strategies.

## Characters extracted from metadata

| Character | Visual description | Source frames |
|-----------|-------------------|---------------|
| **King** | Small beard, stern face. Dark ornate robes over red inner garment. Hair in top knot with tall elaborate dark headpiece (crown-like). Heavier build, older. | shot_001, shot_003, shot_005, shot_007 |
| **Advisor** | Heavier-set, round face, no beard. Dark patterned robes with gold/chevron trim along edges. Simple top knot with horizontal pin. Softer features. | shot_002, shot_006 |
| **Servant** | Young, lean build. Mustache and goatee. Dark robes with geometric patterned sash/vest. Hair in ponytail with simple gold ornament. | shot_004 |

## Setting
- **Throne room** in the Royal Court of Great Ornn
- Warm candlelight from candelabras, wooden lattice screens/windows
- Dark amber color palette, ornate furnishings

## Phase 1: Generate references (`refs-timeline.json`)

Run with `--stage images` to generate only the character/scene references:
```bash
python pipeline.py --timeline-file strategies/d-character-refs/refs-timeline.json --stage images
```

This generates:
- `king-ref` — King character portrait (3 candidates: cel-shaded, painterly, donghua)
- `advisor-ref` — Advisor character portrait (3 candidates)
- `servant-ref` — Servant character portrait (3 candidates)
- `throne-room-ref` — Throne room establishing shot

After reviewing candidates, add `"select": N` to each, then re-run to lock in choices.

Copy the final images to the refs folder:
```bash
cp runs/<run-name>/images/king-ref.png strategies/d-character-refs/refs/characters/king.png
cp runs/<run-name>/images/advisor-ref.png strategies/d-character-refs/refs/characters/advisor.png
cp runs/<run-name>/images/servant-ref.png strategies/d-character-refs/refs/characters/servant.png
cp runs/<run-name>/images/throne-room-ref.png strategies/d-character-refs/refs/scenes/throne-room.png
```

## Phase 2: Generate video (`timeline.json`)

Uses the saved character/scene refs as `reference_images` for each video clip's first frame:
```bash
python pipeline.py --timeline-file strategies/d-character-refs/timeline.json --stage final
```

## Chunk breakdown (Phase 2)
| Clip | Duration | Shots | Character focus | References used |
|------|----------|-------|----------------|-----------------|
| vid-1 | 4s | 1-2 (0-2.9s) | King + Advisor | king.png, advisor.png, throne-room.png |
| vid-2 | 4s | 3-4 (2.9-6.4s) | King + Servant | king.png, servant.png, throne-room.png |
| vid-3 | 8s | 5-7 (6.4-14.9s) | King + Advisor | king.png, advisor.png, throne-room.png |

## Trade-offs
- **Pro**: Best character consistency across clips, reusable references, iterative refinement before committing to expensive video gen
- **Con**: Two-phase workflow (more manual steps), total generation time is longer (refs + videos), reference images guide but don't guarantee consistency
- **Validation**: Candidates on every character ref in phase 1 — this is where you invest review time. Phase 2 videos are fast to iterate once refs are locked.

## DAG shape

### Phase 1 (refs only)
```
Level 1: [king-ref] [advisor-ref] [servant-ref] [throne-room-ref]   (4 concurrent)
```

### Phase 2 (video)
```
Level 1: [img-1] [img-2] [img-3]   (3 concurrent, each uses refs as reference_images)
Level 2: [vid-1] [vid-2] [vid-3]   (3 concurrent)
```

## Folder structure
```
strategies/d-character-refs/
  strategy.md              # This file
  refs-timeline.json       # Phase 1: generate character/scene references
  timeline.json            # Phase 2: video using generated refs
  refs/
    characters/            # Copy final character refs here after Phase 1
      king.png
      advisor.png
      servant.png
    scenes/
      throne-room.png
```
