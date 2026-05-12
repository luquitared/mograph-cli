import type { Route } from "./+types/api.workflows.$slug";
import { db } from "../db/client";
import {
  anonymousHandles,
  workflows,
  workflowVideos,
  workflowFiles,
} from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";

/**
 * GET /api/workflows/:slug
 * Public manifest used by `mograph workflow pull`.
 */
export async function loader({ context, params }: Route.LoaderArgs) {
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const slug = params.slug!;

  const [wf] = await d
    .select({
      id: workflows.id,
      slug: workflows.slug,
      title: workflows.title,
      summary: workflows.summary,
      readmeMd: workflows.readmeMd,
      mainVideoId: workflows.mainVideoId,
      visibility: workflows.visibility,
      createdAt: workflows.createdAt,
      handle: anonymousHandles.handle,
    })
    .from(workflows)
    .innerJoin(
      anonymousHandles,
      eq(workflows.ownerHandleId, anonymousHandles.id),
    )
    .where(eq(workflows.slug, slug))
    .limit(1);

  if (!wf) return json({ error: "not found" }, { status: 404 });
  if (wf.visibility !== "public") {
    return json({ error: "not public" }, { status: 403 });
  }

  const [videos, files] = await Promise.all([
    d
      .select({
        id: workflowVideos.id,
        name: workflowVideos.name,
        path: workflowVideos.path,
        r2Key: workflowVideos.r2Key,
        isMain: workflowVideos.isMain,
        durationS: workflowVideos.durationS,
      })
      .from(workflowVideos)
      .where(eq(workflowVideos.workflowId, wf.id)),
    d
      .select({
        id: workflowFiles.id,
        kind: workflowFiles.kind,
        name: workflowFiles.name,
        path: workflowFiles.path,
        r2Key: workflowFiles.r2Key,
        sizeBytes: workflowFiles.sizeBytes,
      })
      .from(workflowFiles)
      .where(eq(workflowFiles.workflowId, wf.id)),
  ]);

  const manifest = {
    slug: wf.slug,
    title: wf.title,
    summary: wf.summary,
    handle: wf.handle,
    created_at: wf.createdAt,
    readme_md: wf.readmeMd,
    files: [
      ...videos.map((v) => ({
        kind: "video" as const,
        name: v.name,
        path: v.path,
        url: `/cdn/${v.r2Key}`,
        is_main: v.isMain,
        duration_s: v.durationS,
      })),
      ...files.map((f) => ({
        kind: f.kind,
        name: f.name,
        path: f.path,
        url: `/cdn/${f.r2Key}`,
        size_bytes: f.sizeBytes,
      })),
    ],
  };

  return json(manifest);
}
