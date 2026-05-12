import type { Route } from "./+types/api.upload.$token";
import { db } from "../db/client";
import { workflowFiles } from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { verifyUploadToken } from "../lib/sig";

/**
 * PUT /api/upload/:token
 * Body: raw file bytes. Token encodes file_id and target R2 key.
 */
export async function action({ context, request, params }: Route.ActionArgs) {
  if (request.method !== "PUT") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const payload = await verifyUploadToken(env.UPLOAD_SECRET, params.token!);

  const bucket = payload.bucket === "private" ? env.R2_PRIVATE : env.R2_PUBLIC;
  const ct = request.headers.get("content-type") ?? "application/octet-stream";

  if (!request.body) {
    return json({ error: "body required" }, { status: 400 });
  }

  const buf = await request.arrayBuffer();

  if (payload.expectedSha256) {
    const digest = await crypto.subtle.digest("SHA-256", buf);
    const hex = Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    if (hex !== payload.expectedSha256.toLowerCase()) {
      return json(
        { error: "sha256 mismatch", expected: payload.expectedSha256, got: hex },
        { status: 400 },
      );
    }
  }

  await bucket.put(payload.r2Key, buf, {
    httpMetadata: { contentType: ct },
  });

  const d = db(env.DATABASE_URL);
  await d
    .update(workflowFiles)
    .set({ sizeBytes: buf.byteLength })
    .where(eq(workflowFiles.id, payload.fileId));

  return json({ ok: true, key: payload.r2Key, bytes: buf.byteLength });
}
