import { db } from "../db/client";
import { cliDevices } from "../db/schema";
import { eq } from "drizzle-orm";
import { getCurrentSession } from "./session";
import { verifyRequest } from "./sig";

export type Authed = {
  userId: string;
  source: "session" | "cli";
  pubkey?: string;
};

/**
 * Resolve the calling user from either:
 *  - the session cookie (web)
 *  - an X-Mograph-* signed Ed25519 request matched against cli_devices (CLI)
 *
 * Always returns a `{ userId }`; throws a 401 Response otherwise.
 *
 * `bodyBytes` is required when the caller wants signature verification — pass
 * the already-read request body (we can't read it twice).
 */
export async function authenticate(
  request: Request,
  env: { DATABASE_URL: string; SESSION_SECRET: string },
  bodyBytes: Uint8Array = new Uint8Array(),
): Promise<Authed> {
  if (request.headers.get("x-mograph-pubkey")) {
    const { pubkey } = await verifyRequest(request, bodyBytes);
    const d = db(env.DATABASE_URL);
    const [device] = await d
      .select({ userId: cliDevices.userId, pubkey: cliDevices.pubkey })
      .from(cliDevices)
      .where(eq(cliDevices.pubkey, pubkey))
      .limit(1);
    if (!device) {
      throw new Response("pubkey not registered, run mograph login", {
        status: 401,
      });
    }
    // Best-effort touch — don't await, errors are not fatal.
    d.update(cliDevices)
      .set({ lastUsedAt: new Date() })
      .where(eq(cliDevices.pubkey, pubkey))
      .catch(() => {});
    return { userId: device.userId, source: "cli", pubkey };
  }

  const session = await getCurrentSession(request, env.SESSION_SECRET);
  if (session) {
    return { userId: session.user_id, source: "session" };
  }
  throw new Response("not authenticated", { status: 401 });
}
