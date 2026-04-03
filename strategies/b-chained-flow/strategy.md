# Strategy B: Chained Flow

## Approach
3 chained clips with uneven pacing (4s + 4s + 8s = 16s). Only the first clip generates an anime first frame from reference. Each subsequent clip chains from the previous clip's last frame.

## Why this strategy
- **Visual continuity**: Chaining ensures the anime character design stays consistent across all clips — no drift between independently generated frames
- **Dramatic pacing**: Short 4s setup clips build tension, then the 8s final clip covers the dramatic peak (King's angry speech about honor)
- **Single reference entry point**: Only one anime first frame needs to "nail" the style — everything flows from there

## Chunk breakdown
| Clip | Duration | Original shots | Chain source | Content |
|------|----------|---------------|-------------|---------|
| vid-1 | 4s | 1-2 (0-2.9s) | Generated first frame from shot_001 | King stern, Advisor pleads |
| vid-2 | 4s | 3-5 (2.9-10.7s) | Last frame of vid-1 | King agitated, Servant reports, King determined |
| vid-3 | 8s | 5-7 (6.4-14.9s) | Last frame of vid-2 | King's long speech, Advisor worried, King furious |

## Trade-offs
- **Pro**: Best visual continuity, consistent character design, dramatic pacing matches content
- **Con**: Fully sequential execution (slowest of the three strategies), quality degrades if the first frame generation misses the mark, later clips can't be re-run independently
- **Validation**: Uses `candidates` on the initial first frame image — this is the single most important generation since everything chains from it. Get this right and the whole sequence follows.

## DAG shape
```
Level 1: [img-1]           (1 image)
Level 2: [vid-1]           (1 video, needs img-1)
Level 3: [vid-2]           (1 video, needs vid-1 last frame)
Level 4: [vid-3]           (1 video, needs vid-2 last frame)
```
