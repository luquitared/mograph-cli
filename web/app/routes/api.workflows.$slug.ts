import type { Route } from "./+types/api.workflows.$slug";
import { db } from "../db/client";
import {
  users,
  workflows,
  workflowVideos,
  workflowFiles,
} from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { authenticate } from "../lib/auth";

/**
 * DELETE /api/workflows/:slug
 * Owner-only. Deletes DB rows and R2 objects.
 */
export async function action({ context, request, params }: Route.ActionArgs) {
  if (request.method !== "DELETE") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const authed = await authenticate(request, env);

  const d = db(env.DATABASE_URL);
  const [wf] = await d
    .select({
      id: workflows.id,
      slug: workflows.slug,
      ownerUserId: workflows.ownerUserId,
    })
    .from(workflows)
    .where(eq(workflows.slug, params.slug!))
    .limit(1);
  if (!wf) return json({ error: "not found" }, { status: 404 });
  if (wf.ownerUserId !== authed.userId) {
    return json({ error: "not owner" }, { status: 403 });
  }

  let cursor: string | undefined;
  let deletedObjects = 0;
  do {
    const listed = await env.R2_PUBLIC.list({
      prefix: `workflows/${wf.id}/`,
      cursor,
    });
    if (listed.objects.length) {
      await env.R2_PUBLIC.delete(listed.objects.map((o) => o.key));
      deletedObjects += listed.objects.length;
    }
    cursor = listed.truncated ? listed.cursor : undefined;
  } while (cursor);

  await d.delete(workflows).where(eq(workflows.id, wf.id));

  return json({ ok: true, slug: wf.slug, deleted_objects: deletedObjects });
}

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
      handle: users.handle,
      displayName: users.displayName,
      avatarUrl: users.avatarUrl,
      models: workflows.models,
      clipCount: workflows.clipCount,
      totalDurationS: workflows.totalDurationS,
      totalBytes: workflows.totalBytes,
    })
    .from(workflows)
    .innerJoin(users, eq(workflows.ownerUserId, users.id))
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
    display_name: wf.displayName,
    avatar_url: wf.avatarUrl,
    created_at: wf.createdAt,
    readme_md: wf.readmeMd,
    models: wf.models,
    clip_count: wf.clipCount,
    total_duration_s: wf.totalDurationS,
    total_bytes: wf.totalBytes,
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
