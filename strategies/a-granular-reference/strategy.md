# Strategy A: Granular Reference

## Approach
4 independent clips (4s each = 16s total). Every clip generates its own anime first frame using the corresponding original frame as a reference image.

## Why this strategy
- **Maximum concurrency**: All 4 image generations run in parallel, then all 4 video generations run in parallel (2 DAG levels)
- **Per-scene accuracy**: Each clip gets a reference frame closest to its scene, so character expressions and framing stay faithful to the original
- **Uses candidates on clip 1** to explore 3 anime style directions (cel-shaded, watercolor, Ghibli) — pick the best, then apply that style language to all clips

## Chunk breakdown
| Clip | Duration | Original shots | Reference frame | Content |
|------|----------|---------------|-----------------|---------|
| vid-1 | 4s | 1-2 (0-2.9s) | shot_001.jpg | King stern, Advisor pleads |
| vid-2 | 4s | 3-4 (2.9-6.4s) | shot_004.jpg | King agitated, Servant speaks |
| vid-3 | 4s | 5 (6.4-10.7s) | shot_005.jpg | King determined, long speech |
| vid-4 | 4s | 6-7 (10.7-14.9s) | shot_007.jpg | Advisor worried, King angry |

## Trade-offs
- **Pro**: Best scene-to-reference alignment, fastest execution (full parallelism), easy to re-run individual clips
- **Con**: 4 hard cuts between clips, no visual continuity guarantee between clips, character appearance may drift across independently generated frames
- **Validation**: Uses `candidates` on clip 1's first frame to explore anime style — review outputs, set `select`, then update remaining clip prompts to match chosen style

## DAG shape
```
Level 1: [img-1] [img-2] [img-3] [img-4]   (4 concurrent)
Level 2: [vid-1] [vid-2] [vid-3] [vid-4]   (4 concurrent)
```
