import type { Route } from "./+types/api.packs.mine";
import { db } from "../db/client";
import { packs, users } from "../db/schema";
import { desc, eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { authenticate } from "../lib/auth";

/**
 * GET /api/packs/mine
 * Accepts either a session cookie or a signed CLI request.
 */
export async function loader({ context, request }: Route.LoaderArgs) {
  const env = getEnv(context);
  const authed = await authenticate(request, env);

  const d = db(env.DATABASE_URL);
  const [me] = await d
    .select({ id: users.id, handle: users.handle })
    .from(users)
    .where(eq(users.id, authed.userId))
    .limit(1);
  if (!me) return json({ error: "user not found" }, { status: 401 });

  const rows = await d
    .select({
      slug: packs.slug,
      kind: packs.kind,
      title: packs.title,
      summary: packs.summary,
      createdAt: packs.createdAt,
      updatedAt: packs.updatedAt,
      visibility: packs.visibility,
    })
    .from(packs)
    .where(eq(packs.ownerUserId, me.id))
    .orderBy(desc(packs.createdAt));

  return json({ handle: me.handle, packs: rows });
}
