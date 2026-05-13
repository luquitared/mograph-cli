import type { Route } from "./+types/api.workflows";
import { db } from "../db/client";
import {
  users,
  workflows,
  workflowVideos,
  workflowFiles,
} from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { makeUploadToken } from "../lib/sig";
import { authenticate } from "../lib/auth";

const RESERVED_SLUGS = new Set(["mine", "new", "edit"]);

type Declared = {
  name: string;
  path: string;
  kind: "video" | "timeline" | "md" | "txt" | "pack";
  size_bytes?: number;
  sha256?: string;
  is_main_video?: boolean;
  duration_s?: number;
};

type Metadata = {
  models?: string[];
  clip_count?: number;
  total_duration_s?: number;
};

type PushBody = {
  slug?: string;
  title: string;
  summary?: string;
  readme_md: string;
  files: Declared[];
  metadata?: Metadata;
};

function slugify(s: string): string {
  return (
    s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "")
      .slice(0, 60) || "workflow"
  );
}

function r2KeyFor(workflowId: string, path: string): string {
  const safe = path
    .split("/")
    .map((seg) => seg.replace(/[^a-zA-Z0-9._-]+/g, "_"))
    .join("/");
  return `workflows/${workflowId}/${safe}`;
}

function sanitizePath(p: string): string | null {
  if (!p) return null;
  const norm = p.replace(/\\/g, "/").replace(/^\/+/, "");
  if (norm.split("/").some((s) => s === "" || s === "." || s === "..")) {
    return null;
  }
  if (norm.length > 240) return null;
  return norm;
}

export async function action({ context, request }: Route.ActionArgs) {
  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);

  const bodyBytes = new Uint8Array(await request.arrayBuffer());
  const authed = await authenticate(request, env, bodyBytes);

  const [me] = await d
    .select({ id: users.id, handle: users.handle })
    .from(users)
    .where(eq(users.id, authed.userId))
    .limit(1);
  if (!me) return json({ error: "user not found" }, { status: 401 });

  let body: PushBody;
  try {
    body = JSON.parse(new TextDecoder().decode(bodyBytes));
  } catch {
    return json({ error: "invalid json" }, { status: 400 });
  }
  if (!body.title || !body.readme_md || !Array.isArray(body.files)) {
    return json({ error: "title, readme_md, files required" }, { status: 400 });
  }

  const requestedSlug = body.slug ? slugify(body.slug) : null;
  let slug: string;
  let existingForUpdate: { id: string; ownerUserId: string } | null = null;

  if (requestedSlug) {
    if (RESERVED_SLUGS.has(requestedSlug)) {
      return json({ error: `slug '${requestedSlug}' is reserved` }, { status: 400 });
    }
    const [existing] = await d
      .select({ id: workflows.id, ownerUserId: workflows.ownerUserId })
      .from(workflows)
      .where(eq(workflows.slug, requestedSlug))
      .limit(1);
    if (existing) {
      if (existing.ownerUserId !== me.id) {
        return json(
          { error: `slug '${requestedSlug}' is taken by another author` },
          { status: 409 },
        );
      }
      existingForUpdate = existing;
    }
    slug = requestedSlug;
  } else {
    slug = slugify(body.title);
    for (let i = 0; i < 6; i++) {
      const conflict = await d
        .select({ id: workflows.id })
        .from(workflows)
        .where(eq(workflows.slug, slug))
        .limit(1);
      if (!conflict[0]) break;
      slug = `${slugify(body.title)}-${Math.floor(Math.random() * 9000 + 1000)}`;
    }
  }

  // If updating an existing workflow we own: blow away the prior R2 objects
  // and DB rows, then recreate cleanly.
  if (existingForUpdate) {
    let cursor: string | undefined;
    do {
      const listed = await env.R2_PUBLIC.list({
        prefix: `workflows/${existingForUpdate.id}/`,
        cursor,
      });
      if (listed.objects.length) {
        await env.R2_PUBLIC.delete(listed.objects.map((o) => o.key));
      }
      cursor = listed.truncated ? listed.cursor : undefined;
    } while (cursor);
    await d.delete(workflows).where(eq(workflows.id, existingForUpdate.id));
  }

  const meta = body.metadata ?? {};
  const totalBytes = body.files.reduce(
    (sum, f) => sum + (typeof f.size_bytes === "number" ? f.size_bytes : 0),
    0,
  );
  const models = Array.isArray(meta.models)
    ? Array.from(
        new Set(
          meta.models
            .filter((m) => typeof m === "string" && m)
            .map((m) => m.slice(0, 80)),
        ),
      ).slice(0, 24)
    : null;

  const [wf] = await d
    .insert(workflows)
    .values({
      slug,
      title: body.title.slice(0, 200),
      summary: body.summary?.slice(0, 500) ?? null,
      readmeMd: body.readme_md.slice(0, 200_000),
      ownerUserId: me.id,
      visibility: "public",
      models: models && models.length ? models : null,
      clipCount: typeof meta.clip_count === "number" ? meta.clip_count : null,
      totalDurationS:
        typeof meta.total_duration_s === "number" ? meta.total_duration_s : null,
      totalBytes: totalBytes || null,
    })
    .returning();

  const expiresAt = Math.floor(Date.now() / 1000) + 3600;
  const out: Array<{
    name: string;
    path: string;
    kind: string;
    file_id: string;
    upload_url: string;
  }> = [];
  let mainVideoId: string | null = null;

  for (const f of body.files) {
    const safePath = sanitizePath(f.path ?? f.name);
    if (!safePath) {
      return json({ error: `bad path: ${f.path}` }, { status: 400 });
    }
    const r2Key = r2KeyFor(wf.id, safePath);
    let fileId: string;

    if (f.kind === "video") {
      const [row] = await d
        .insert(workflowVideos)
        .values({
          workflowId: wf.id,
          name: f.name,
          path: safePath,
          r2Key,
          durationS: f.duration_s ?? null,
          isMain: !!f.is_main_video,
        })
        .returning();
      fileId = row.id;
      if (f.is_main_video) mainVideoId = row.id;
    } else {
      const [row] = await d
        .insert(workflowFiles)
        .values({
          workflowId: wf.id,
          kind: f.kind,
          name: f.name,
          path: safePath,
          r2Key,
          sizeBytes: f.size_bytes ?? null,
        })
        .returning();
      fileId = row.id;
    }

    const token = await makeUploadToken(env.UPLOAD_SECRET, {
      fileId,
      r2Key,
      bucket: "public",
      expectedSha256: f.sha256,
      expiresAt,
    });
    out.push({
      name: f.name,
      path: safePath,
      kind: f.kind,
      file_id: fileId,
      upload_url: `/api/upload/${token}`,
    });
  }

  if (mainVideoId) {
    await d.update(workflows).set({ mainVideoId }).where(eq(workflows.id, wf.id));
  }

  return json({
    workflow_id: wf.id,
    slug: wf.slug,
    url: `/workflows/${wf.slug}`,
    handle: me.handle,
    uploads: out,
  });
}
