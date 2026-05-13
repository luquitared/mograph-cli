import type { Route } from "./+types/api.claim.start";
import { db } from "../db/client";
import { anonymousHandles, deviceAuth } from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { verifyRequest } from "../lib/sig";

const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no I/O/1/0

function generateCode(): string {
  const buf = new Uint8Array(8);
  crypto.getRandomValues(buf);
  let s = "";
  for (let i = 0; i < buf.length; i++) {
    s += ALPHABET[buf[i] % ALPHABET.length];
    if (i === 3) s += "-";
  }
  return s;
}

/**
 * POST /api/claim/start
 * Signed by the CLI's handle. Creates a one-time pairing code that, when
 * confirmed by a signed-in browser, links this handle to that user.
 */
export async function action({ context, request }: Route.ActionArgs) {
  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const bodyBytes = new Uint8Array(await request.arrayBuffer());
  const { pubkey } = await verifyRequest(request, bodyBytes);

  const [handle] = await d
    .select()
    .from(anonymousHandles)
    .where(eq(anonymousHandles.pubkey, pubkey))
    .limit(1);
  if (!handle) {
    return json({ error: "pubkey not registered" }, { status: 401 });
  }
  if (handle.claimedByUserId) {
    return json(
      { error: "handle already claimed", handle: handle.handle },
      { status: 409 },
    );
  }

  const expiresAt = new Date(Date.now() + 10 * 60 * 1000);
  let code = generateCode();
  for (let i = 0; i < 5; i++) {
    try {
      await d.insert(deviceAuth).values({
        code,
        handleId: handle.id,
        expiresAt,
      });
      break;
    } catch (e: any) {
      if (e?.code === "23505") {
        code = generateCode();
        continue;
      }
      throw e;
    }
  }

  return json({
    code,
    handle: handle.handle,
    expires_at: expiresAt.toISOString(),
    pair_url: `/claim?code=${encodeURIComponent(code)}`,
  });
}
