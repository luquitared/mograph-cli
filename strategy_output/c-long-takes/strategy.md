# Strategy C: Two Long Takes with Timestamp Prompting

## Approach
2 clips (8s + 8s = 16s). Each clip generates its own anime first frame from a different reference. Video prompts use internal timestamp annotations to guide scene progression within each clip.

## Why this strategy
- **Fewest cuts**: Only 1 seam in the entire video — less chance of visual jarring
- **Timestamp prompting**: Instead of splitting scenes into many short clips, embed the scene beats *inside* the prompt with time markers (e.g., `[0:00] King sits sternly [0:03] leans forward`). Lets veo handle the pacing internally for more natural motion
- **Concurrent execution**: Both clips generate their own first frames independently → 2 images + 2 videos can partially overlap in the DAG
- **Different reference frames**: Clip 1 references shot_001 (King), clip 2 references shot_005 (King angry) — each anchors its half of the scene

## Chunk breakdown
| Clip | Duration | Original shots | Reference frame | Content |
|------|----------|---------------|-----------------|---------|
| vid-1 | 8s | 1-4 (0-6.4s) | shot_001.jpg | Opening exchange: King stern → Advisor pleads → Servant reports |
| vid-2 | 8s | 5-7 (6.4-14.9s) | shot_005.jpg | Escalation: King determined speech → Advisor worried → King furious |

## Trade-offs
- **Pro**: Most natural motion (fewer cuts, longer generation = more coherent movement), fastest after Strategy A (partial concurrency), timestamp prompting lets veo pace the internal beats
- **Con**: Less control over exact scene beats (veo interprets timestamps loosely), only 2 reference points so mid-scene characters may drift, harder to re-do just one moment without regenerating the whole 8s clip
- **Validation**: No candidates here — instead, lean on the two reference frames to anchor style. If results are off, add candidates on the first frames in a second pass.

## DAG shape
```
Level 1: [img-1] [img-2]   (2 concurrent)
Level 2: [vid-1] [vid-2]   (2 concurrent)
```
