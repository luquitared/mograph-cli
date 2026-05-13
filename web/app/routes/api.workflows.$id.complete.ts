import type { Route } from "./+types/api.workflows.$id.complete";
import { db } from "../db/client";
import { workflows } from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { authenticate } from "../lib/auth";

/**
 * POST /api/workflows/:id/complete
 * Optional finalizer. Currently just bumps updated_at after the owner uploads
 * all files. Reserved for future per-completion side-effects.
 */
export async function action({ context, request, params }: Route.ActionArgs) {
  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const bodyBytes = new Uint8Array(await request.arrayBuffer());
  const authed = await authenticate(request, env, bodyBytes);

  const d = db(env.DATABASE_URL);
  const [wf] = await d
    .select({
      id: workflows.id,
      ownerUserId: workflows.ownerUserId,
      slug: workflows.slug,
    })
    .from(workflows)
    .where(eq(workflows.id, params.id!))
    .limit(1);
  if (!wf) return json({ error: "workflow not found" }, { status: 404 });
  if (wf.ownerUserId !== authed.userId) {
    return json({ error: "not owner" }, { status: 403 });
  }

  await d
    .update(workflows)
    .set({ updatedAt: new Date() })
    .where(eq(workflows.id, wf.id));

  return json({ ok: true, slug: wf.slug });
}
