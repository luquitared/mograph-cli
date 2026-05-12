import type { Route } from "./+types/api.handles";
import { db } from "../db/client";
import { anonymousHandles } from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { randomHandle } from "../lib/handles";
import { b64decode } from "../lib/sig";

/**
 * POST /api/handles
 * Body: { pubkey: string (base64, 32 bytes Ed25519) }
 * Idempotent on pubkey — re-registering returns the existing handle.
 */
export async function action({ context, request }: Route.ActionArgs) {
  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);

  const body = (await request.json()) as { pubkey?: string };
  if (!body.pubkey || typeof body.pubkey !== "string") {
    return json({ error: "pubkey required" }, { status: 400 });
  }
  let bytes: Uint8Array;
  try {
    bytes = b64decode(body.pubkey);
  } catch {
    return json({ error: "pubkey not base64" }, { status: 400 });
  }
  if (bytes.length !== 32) {
    return json({ error: "pubkey must be 32 bytes" }, { status: 400 });
  }

  const existing = await d
    .select()
    .from(anonymousHandles)
    .where(eq(anonymousHandles.pubkey, body.pubkey))
    .limit(1);
  if (existing[0]) {
    return json({
      handle: existing[0].handle,
      handle_id: existing[0].id,
      claimed: !!existing[0].claimedByUserId,
    });
  }

  for (let attempt = 0; attempt < 5; attempt++) {
    const handle = randomHandle();
    try {
      const [row] = await d
        .insert(anonymousHandles)
        .values({ handle, pubkey: body.pubkey })
        .returning();
      return json({ handle: row.handle, handle_id: row.id, claimed: false });
    } catch (e: any) {
      if (e?.code === "23505") continue;
      throw e;
    }
  }
  return json({ error: "could not allocate handle" }, { status: 500 });
}
