import type { Route } from "./+types/api.workflows.mine";
import { db } from "../db/client";
import { anonymousHandles, workflows } from "../db/schema";
import { desc, eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { verifyRequest } from "../lib/sig";

/**
 * GET /api/workflows/mine
 * Signed (Ed25519). Returns workflows owned by the handle behind the pubkey.
 */
export async function loader({ context, request }: Route.LoaderArgs) {
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const { pubkey } = await verifyRequest(request, new Uint8Array());

  const [handle] = await d
    .select()
    .from(anonymousHandles)
    .where(eq(anonymousHandles.pubkey, pubkey))
    .limit(1);
  if (!handle) {
    return json({ error: "pubkey not registered" }, { status: 401 });
  }

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
    .where(eq(workflows.ownerHandleId, handle.id))
    .orderBy(desc(workflows.createdAt));

  return json({ handle: handle.handle, workflows: rows });
}
