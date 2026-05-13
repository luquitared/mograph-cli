import type { Route } from "./+types/api.claim.status";
import { db } from "../db/client";
import { anonymousHandles, deviceAuth, users } from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";

/**
 * GET /api/claim/status?code=<code>
 * Public — used by the CLI to poll for claim completion.
 */
export async function loader({ context, request }: Route.LoaderArgs) {
  const env = getEnv(context);
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  if (!code) return json({ error: "code required" }, { status: 400 });

  const d = db(env.DATABASE_URL);
  const [row] = await d
    .select({
      code: deviceAuth.code,
      consumedAt: deviceAuth.consumedAt,
      expiresAt: deviceAuth.expiresAt,
      handle: anonymousHandles.handle,
      handleId: anonymousHandles.id,
      claimedByUserId: anonymousHandles.claimedByUserId,
      userHandle: users.handle,
      userDisplayName: users.displayName,
    })
    .from(deviceAuth)
    .innerJoin(
      anonymousHandles,
      eq(deviceAuth.handleId, anonymousHandles.id),
    )
    .leftJoin(users, eq(anonymousHandles.claimedByUserId, users.id))
    .where(eq(deviceAuth.code, code))
    .limit(1);

  if (!row) return json({ status: "not_found" }, { status: 404 });
  const now = Date.now();
  if (row.expiresAt.getTime() < now && !row.consumedAt) {
    return json({ status: "expired" });
  }
  if (row.consumedAt && row.claimedByUserId) {
    return json({
      status: "claimed",
      handle: row.handle,
      user: row.userHandle,
      display_name: row.userDisplayName,
    });
  }
  return json({ status: "pending", handle: row.handle });
}
