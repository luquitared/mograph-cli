import type { Route } from "./+types/api.workflows";
import { db } from "../db/client";
import {
  anonymousHandles,
  workflows,
  workflowVideos,
  workflowFiles,
} from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { verifyRequest, makeUploadToken } from "../lib/sig";

type Declared = {
  name: string;
  path: string;
  kind: "video" | "timeline" | "md" | "txt" | "pack";
  size_bytes?: number;
  sha256?: string;
  is_main_video?: boolean;
  duration_s?: number;
};

type PushBody = {
  slug?: string;
  title: string;
  summary?: string;
  readme_md: string;
  files: Declared[];
};

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .slice(0, 60) || "workflow";
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
  const { pubkey } = await verifyRequest(request, bodyBytes);

  const [handle] = await d
    .select()
    .from(anonymousHandles)
    .where(eq(anonymousHandles.pubkey, pubkey))
    .limit(1);
  if (!handle) {
    return json({ error: "pubkey not registered, run mograph login" }, { status: 401 });
  }

  let body: PushBody;
  try {
    body = JSON.parse(new TextDecoder().decode(bodyBytes));
  } catch {
    return json({ error: "invalid json" }, { status: 400 });
  }
  if (!body.title || !body.readme_md || !Array.isArray(body.files)) {
    return json({ error: "title, readme_md, files required" }, { status: 400 });
  }

  let slug = body.slug ? slugify(body.slug) : slugify(body.title);
  for (let i = 0; i < 6; i++) {
    const conflict = await d
      .select({ id: workflows.id })
      .from(workflows)
      .where(eq(workflows.slug, slug))
      .limit(1);
    if (!conflict[0]) break;
    slug = `${slugify(body.title)}-${Math.floor(Math.random() * 9000 + 1000)}`;
  }

  const [wf] = await d
    .insert(workflows)
    .values({
      slug,
      title: body.title.slice(0, 200),
      summary: body.summary?.slice(0, 500) ?? null,
      readmeMd: body.readme_md.slice(0, 200_000),
      ownerHandleId: handle.id,
      visibility: "public",
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
    handle: handle.handle,
    uploads: out,
  });
}
