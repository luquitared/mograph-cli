import type { Route } from "./+types/api.packs";
import { db } from "../db/client";
import { packFiles, packs, users } from "../db/schema";
import { and, desc, eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { makeUploadToken } from "../lib/sig";
import { authenticate } from "../lib/auth";

const RESERVED_SLUGS = new Set(["mine", "new", "edit"]);
const ALLOWED_KINDS = new Set(["asset", "style"]);

type Declared = {
  name: string;
  path: string;
  size_bytes?: number;
  sha256?: string;
};

type PushBody = {
  slug?: string;
  kind: "asset" | "style";
  title: string;
  summary?: string;
  readme_md?: string;
  files: Declared[];
};

function slugify(s: string): string {
  return (
    s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "")
      .slice(0, 60) || "pack"
  );
}

function r2KeyFor(packId: string, path: string): string {
  const safe = path
    .split("/")
    .map((seg) => seg.replace(/[^a-zA-Z0-9._-]+/g, "_"))
    .join("/");
  return `packs/${packId}/${safe}`;
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

export async function loader({ context, request }: Route.LoaderArgs) {
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const url = new URL(request.url);
  const kindParam = url.searchParams.get("kind");
  const kind = kindParam && ALLOWED_KINDS.has(kindParam) ? kindParam : null;

  const where = kind
    ? and(eq(packs.visibility, "public"), eq(packs.kind, kind))
    : eq(packs.visibility, "public");

  const rows = await d
    .select({
      slug: packs.slug,
      kind: packs.kind,
      title: packs.title,
      summary: packs.summary,
      totalBytes: packs.totalBytes,
      totalFiles: packs.totalFiles,
      createdAt: packs.createdAt,
      handle: users.handle,
      displayName: users.displayName,
    })
    .from(packs)
    .innerJoin(users, eq(packs.ownerUserId, users.id))
    .where(where)
    .orderBy(desc(packs.createdAt));

  return json({ packs: rows });
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
  if (!body.title || !body.kind || !Array.isArray(body.files)) {
    return json({ error: "title, kind, files required" }, { status: 400 });
  }
  if (!ALLOWED_KINDS.has(body.kind)) {
    return json(
      { error: `kind must be one of: ${[...ALLOWED_KINDS].join(", ")}` },
      { status: 400 },
    );
  }

  const requestedSlug = body.slug ? slugify(body.slug) : null;
  let slug: string;
  let existingForUpdate: { id: string; ownerUserId: string } | null = null;

  if (requestedSlug) {
    if (RESERVED_SLUGS.has(requestedSlug)) {
      return json({ error: `slug '${requestedSlug}' is reserved` }, { status: 400 });
    }
    const [existing] = await d
      .select({ id: packs.id, ownerUserId: packs.ownerUserId })
      .from(packs)
      .where(eq(packs.slug, requestedSlug))
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
        .select({ id: packs.id })
        .from(packs)
        .where(eq(packs.slug, slug))
        .limit(1);
      if (!conflict[0]) break;
      slug = `${slugify(body.title)}-${Math.floor(Math.random() * 9000 + 1000)}`;
    }
  }

  // If updating an existing pack we own: blow away the prior R2 objects
  // and DB rows, then recreate cleanly.
  if (existingForUpdate) {
    let cursor: string | undefined;
    do {
      const listed = await env.R2_PUBLIC.list({
        prefix: `packs/${existingForUpdate.id}/`,
        cursor,
      });
      if (listed.objects.length) {
        await env.R2_PUBLIC.delete(listed.objects.map((o) => o.key));
      }
      cursor = listed.truncated ? listed.cursor : undefined;
    } while (cursor);
    await d.delete(packs).where(eq(packs.id, existingForUpdate.id));
  }

  const totalBytes = body.files.reduce(
    (sum, f) => sum + (typeof f.size_bytes === "number" ? f.size_bytes : 0),
    0,
  );

  const [pk] = await d
    .insert(packs)
    .values({
      slug,
      kind: body.kind,
      title: body.title.slice(0, 200),
      summary: body.summary?.slice(0, 500) ?? null,
      readmeMd: (body.readme_md ?? "").slice(0, 200_000),
      ownerUserId: me.id,
      visibility: "public",
      totalBytes: totalBytes || null,
      totalFiles: body.files.length || null,
    })
    .returning();

  const expiresAt = Math.floor(Date.now() / 1000) + 3600;
  const out: Array<{
    name: string;
    path: string;
    file_id: string;
    upload_url: string;
  }> = [];

  for (const f of body.files) {
    const safePath = sanitizePath(f.path ?? f.name);
    if (!safePath) {
      return json({ error: `bad path: ${f.path}` }, { status: 400 });
    }
    const r2Key = r2KeyFor(pk.id, safePath);
    const [row] = await d
      .insert(packFiles)
      .values({
        packId: pk.id,
        name: f.name,
        path: safePath,
        r2Key,
        sizeBytes: f.size_bytes ?? null,
      })
      .returning();

    const token = await makeUploadToken(env.UPLOAD_SECRET, {
      fileId: row.id,
      r2Key,
      bucket: "public",
      table: "pack_files",
      expectedSha256: f.sha256,
      expiresAt,
    });
    out.push({
      name: f.name,
      path: safePath,
      file_id: row.id,
      upload_url: `/api/upload/${token}`,
    });
  }

  return json({
    pack_id: pk.id,
    slug: pk.slug,
    kind: pk.kind,
    url: `/packs/${pk.slug}`,
    handle: me.handle,
    uploads: out,
  });
}
