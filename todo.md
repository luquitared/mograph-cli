# TODO: Visual Style Not Connected to Pipeline

## Issue

The frontend's "Visual Style" selection is collected but never passed to the video generation pipeline.

## Current State

### Frontend (`saas-starter-kit/pages/teams/[slug]/videos/create.tsx`)

- Dropdown with options: `infographic`, `brutalist-editorial`, `fintech`, `corporate`, `minimal`
- Value stored in `project.style`

### Backend (`saas-starter-kit/pages/api/teams/[slug]/videos/[id]/generate.ts:206`)

```typescript
video_model: project.style === 'fast' ? 'fast' : 'quality',
```

- Only checks if `style === 'fast'` (never true with current options)
- Visual style value is **not** forwarded to the pipeline

### Pipeline (`pipeline.py`)

- Script schema supports a `style` field
- `brand_style_analysis` exists for colors/typography/motifs
- `styles.py` referenced in CLAUDE.md but doesn't exist

## Fix Required (not decided, user must make final decision)

1. Pass `style` to the pipeline payload in `generate.ts`
2. Create `styles.py` with style definitions, OR
3. Include style in `script_json` generation prompt
4. Update pipeline to use the style when generating scripts/images
