import type { Route } from "./+types/api.claim.this-browser";
import { db } from "../db/client";
import { anonymousHandles } from "../db/schema";
import { and, eq, isNull } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { getCurrentSession } from "../lib/session";
import { verifyRequest } from "../lib/sig";

/**
 * POST /api/claim/this-browser
 * Session cookie (proves who you are) + Ed25519 signature header (proves
 * you hold the private key for the browser's handle). Links them.
 */
export async function action({ context, request }: Route.ActionArgs) {
  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const session = await getCurrentSession(request, env.SESSION_SECRET);
  if (!session) {
    return json({ error: "not signed in" }, { status: 401 });
  }

  const bodyBytes = new Uint8Array(await request.arrayBuffer());
  const { pubkey } = await verifyRequest(request, bodyBytes);

  const d = db(env.DATABASE_URL);
  const [handle] = await d
    .select()
    .from(anonymousHandles)
    .where(eq(anonymousHandles.pubkey, pubkey))
    .limit(1);
  if (!handle) {
    return json({ error: "pubkey not registered" }, { status: 404 });
  }
  if (handle.claimedByUserId && handle.claimedByUserId !== session.user_id) {
    return json(
      { error: "handle already claimed by another user" },
      { status: 409 },
    );
  }

  await d
    .update(anonymousHandles)
    .set({ claimedByUserId: session.user_id })
    .where(
      and(
        eq(anonymousHandles.id, handle.id),
        isNull(anonymousHandles.claimedByUserId),
      ),
    );

  return json({ ok: true, handle: handle.handle });
}
