import type { Route } from "./+types/api.workflows.$id.complete";
import { db } from "../db/client";
import { workflows, anonymousHandles } from "../db/schema";
import { and, eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { verifyRequest } from "../lib/sig";

/**
 * POST /api/workflows/:id/complete
 * Optional finalizer — sets updated_at, owner verifies, etc.
 * Currently a no-op success because workflow row is already public after
 * /api/workflows. Reserved for future: e.g. require N completed uploads.
 */
export async function action({ context, request, params }: Route.ActionArgs) {
  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const bodyBytes = new Uint8Array(await request.arrayBuffer());
  const { pubkey } = await verifyRequest(request, bodyBytes);

  const [wf] = await d
    .select({
      id: workflows.id,
      ownerHandleId: workflows.ownerHandleId,
      handlePubkey: anonymousHandles.pubkey,
      slug: workflows.slug,
    })
    .from(workflows)
    .innerJoin(
      anonymousHandles,
      eq(workflows.ownerHandleId, anonymousHandles.id),
    )
    .where(eq(workflows.id, params.id!))
    .limit(1);

  if (!wf) return json({ error: "workflow not found" }, { status: 404 });
  if (wf.handlePubkey !== pubkey) {
    return json({ error: "not owner" }, { status: 403 });
  }

  await d
    .update(workflows)
    .set({ updatedAt: new Date() })
    .where(eq(workflows.id, wf.id));

  return json({ ok: true, slug: wf.slug });
}
