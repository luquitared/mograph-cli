import type { Route } from "./+types/api.packs.$slug";
import { db } from "../db/client";
import { packFiles, packs, users } from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { authenticate } from "../lib/auth";

/**
 * DELETE /api/packs/:slug
 * Owner-only. Deletes DB rows and R2 objects.
 */
export async function action({ context, request, params }: Route.ActionArgs) {
  if (request.method !== "DELETE") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const authed = await authenticate(request, env);

  const d = db(env.DATABASE_URL);
  const [pk] = await d
    .select({
      id: packs.id,
      slug: packs.slug,
      ownerUserId: packs.ownerUserId,
    })
    .from(packs)
    .where(eq(packs.slug, params.slug!))
    .limit(1);
  if (!pk) return json({ error: "not found" }, { status: 404 });
  if (pk.ownerUserId !== authed.userId) {
    return json({ error: "not owner" }, { status: 403 });
  }

  let cursor: string | undefined;
  let deletedObjects = 0;
  do {
    const listed = await env.R2_PUBLIC.list({
      prefix: `packs/${pk.id}/`,
      cursor,
    });
    if (listed.objects.length) {
      await env.R2_PUBLIC.delete(listed.objects.map((o) => o.key));
      deletedObjects += listed.objects.length;
    }
    cursor = listed.truncated ? listed.cursor : undefined;
  } while (cursor);

  await d.delete(packs).where(eq(packs.id, pk.id));

  return json({ ok: true, slug: pk.slug, deleted_objects: deletedObjects });
}

/**
 * GET /api/packs/:slug
 * Public manifest used by `mograf pack pull`.
 */
export async function loader({ context, params }: Route.LoaderArgs) {
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const slug = params.slug!;

  const [pk] = await d
    .select({
      id: packs.id,
      slug: packs.slug,
      kind: packs.kind,
      title: packs.title,
      summary: packs.summary,
      readmeMd: packs.readmeMd,
      visibility: packs.visibility,
      totalBytes: packs.totalBytes,
      totalFiles: packs.totalFiles,
      createdAt: packs.createdAt,
      handle: users.handle,
      displayName: users.displayName,
      avatarUrl: users.avatarUrl,
    })
    .from(packs)
    .innerJoin(users, eq(packs.ownerUserId, users.id))
    .where(eq(packs.slug, slug))
    .limit(1);

  if (!pk) return json({ error: "not found" }, { status: 404 });
  if (pk.visibility !== "public") {
    return json({ error: "not public" }, { status: 403 });
  }

  const files = await d
    .select({
      id: packFiles.id,
      name: packFiles.name,
      path: packFiles.path,
      r2Key: packFiles.r2Key,
      sizeBytes: packFiles.sizeBytes,
    })
    .from(packFiles)
    .where(eq(packFiles.packId, pk.id));

  return json({
    slug: pk.slug,
    kind: pk.kind,
    title: pk.title,
    summary: pk.summary,
    handle: pk.handle,
    display_name: pk.displayName,
    avatar_url: pk.avatarUrl,
    created_at: pk.createdAt,
    readme_md: pk.readmeMd,
    total_bytes: pk.totalBytes,
    total_files: pk.totalFiles,
    files: files.map((f) => ({
      name: f.name,
      path: f.path,
      url: `/cdn/${f.r2Key}`,
      size_bytes: f.sizeBytes,
    })),
  });
}
