import type { Route } from "./+types/api.workflows.mine";
import { db } from "../db/client";
import { users, workflows } from "../db/schema";
import { desc, eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { authenticate } from "../lib/auth";

/**
 * GET /api/workflows/mine
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
      slug: workflows.slug,
      title: workflows.title,
      summary: workflows.summary,
      createdAt: workflows.createdAt,
      updatedAt: workflows.updatedAt,
      visibility: workflows.visibility,
    })
    .from(workflows)
    .where(eq(workflows.ownerUserId, me.id))
    .orderBy(desc(workflows.createdAt));

  return json({ handle: me.handle, workflows: rows });
}
