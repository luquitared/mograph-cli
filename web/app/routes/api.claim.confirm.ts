import type { Route } from "./+types/api.claim.confirm";
import { db } from "../db/client";
import { anonymousHandles, deviceAuth } from "../db/schema";
import { and, eq, isNull } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { getCurrentSession } from "../lib/session";

/**
 * POST /api/claim/confirm
 * Body: { code: string }
 * Requires a signed-in user (session cookie). Looks up the pairing code,
 * marks it consumed, and links the underlying handle to the user.
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

  const body = (await request.json()) as { code?: string };
  const code = body.code?.trim();
  if (!code) return json({ error: "code required" }, { status: 400 });

  const d = db(env.DATABASE_URL);
  const [row] = await d
    .select({
      code: deviceAuth.code,
      handleId: deviceAuth.handleId,
      expiresAt: deviceAuth.expiresAt,
      consumedAt: deviceAuth.consumedAt,
      handle: anonymousHandles.handle,
      claimedByUserId: anonymousHandles.claimedByUserId,
    })
    .from(deviceAuth)
    .innerJoin(
      anonymousHandles,
      eq(deviceAuth.handleId, anonymousHandles.id),
    )
    .where(eq(deviceAuth.code, code))
    .limit(1);

  if (!row) return json({ error: "code not found" }, { status: 404 });
  if (row.consumedAt) {
    return json({ error: "code already used" }, { status: 410 });
  }
  if (row.expiresAt.getTime() < Date.now()) {
    return json({ error: "code expired" }, { status: 410 });
  }
  if (row.claimedByUserId && row.claimedByUserId !== session.user_id) {
    return json({ error: "handle already claimed by another user" }, { status: 409 });
  }

  await d
    .update(anonymousHandles)
    .set({ claimedByUserId: session.user_id })
    .where(
      and(
        eq(anonymousHandles.id, row.handleId),
        isNull(anonymousHandles.claimedByUserId),
      ),
    );
  await d
    .update(deviceAuth)
    .set({ consumedAt: new Date() })
    .where(eq(deviceAuth.code, code));

  return json({ ok: true, handle: row.handle });
}
