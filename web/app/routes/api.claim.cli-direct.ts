import type { Route } from "./+types/api.claim.cli-direct";
import { db } from "../db/client";
import { anonymousHandles, users } from "../db/schema";
import { and, eq, isNull } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { verifyRequest } from "../lib/sig";

async function makeHandleFromGithub(d: ReturnType<typeof db>, login: string): Promise<string> {
  const base = login.toLowerCase().replace(/[^a-z0-9-]/g, "-").slice(0, 32) || "user";
  for (let i = 0; i < 6; i++) {
    const candidate = i === 0 ? base : `${base}-${Math.floor(Math.random() * 9000 + 1000)}`;
    const [conflict] = await d
      .select({ id: users.id })
      .from(users)
      .where(eq(users.handle, candidate))
      .limit(1);
    if (!conflict) return candidate;
  }
  return `${base}-${Date.now().toString(36)}`;
}

/**
 * POST /api/claim/cli-direct
 * Body: { github_access_token: string }
 * Signed by the CLI's Ed25519 handle. Server verifies the GitHub token, looks
 * up / creates the user, and links the handle. Used by `mograph claim` after
 * a successful GitHub device-flow exchange.
 */
export async function action({ context, request }: Route.ActionArgs) {
  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const bodyBytes = new Uint8Array(await request.arrayBuffer());
  const { pubkey } = await verifyRequest(request, bodyBytes);

  let body: { github_access_token?: string };
  try {
    body = JSON.parse(new TextDecoder().decode(bodyBytes));
  } catch {
    return json({ error: "invalid json" }, { status: 400 });
  }
  const token = body.github_access_token?.trim();
  if (!token) {
    return json({ error: "github_access_token required" }, { status: 400 });
  }

  const ghResp = await fetch("https://api.github.com/user", {
    headers: {
      authorization: `Bearer ${token}`,
      "user-agent": "mograph-cli",
      accept: "application/vnd.github+json",
    },
  });
  if (!ghResp.ok) {
    return json({ error: "github token rejected" }, { status: 401 });
  }
  const ghUser = (await ghResp.json()) as {
    id: number;
    login: string;
    name?: string | null;
    email?: string | null;
    avatar_url?: string | null;
  };
  const githubId = String(ghUser.id);

  let email = ghUser.email ?? null;
  if (!email) {
    try {
      const emailsResp = await fetch("https://api.github.com/user/emails", {
        headers: {
          authorization: `Bearer ${token}`,
          "user-agent": "mograph-cli",
          accept: "application/vnd.github+json",
        },
      });
      if (emailsResp.ok) {
        const emails = (await emailsResp.json()) as Array<{
          email: string;
          primary: boolean;
          verified: boolean;
        }>;
        const primary = emails.find((e) => e.primary && e.verified);
        email = primary?.email ?? null;
      }
    } catch {
      /* ignore */
    }
  }

  const d = db(env.DATABASE_URL);
  let [user] = await d
    .select()
    .from(users)
    .where(eq(users.githubId, githubId))
    .limit(1);
  if (!user) {
    const handle = await makeHandleFromGithub(d, ghUser.login);
    [user] = await d
      .insert(users)
      .values({
        handle,
        email,
        githubId,
        githubLogin: ghUser.login,
        displayName: ghUser.name ?? ghUser.login,
        avatarUrl: ghUser.avatar_url ?? null,
      })
      .returning();
  } else {
    [user] = await d
      .update(users)
      .set({
        email: email ?? user.email,
        githubLogin: ghUser.login,
        displayName: ghUser.name ?? user.displayName,
        avatarUrl: ghUser.avatar_url ?? user.avatarUrl,
      })
      .where(eq(users.id, user.id))
      .returning();
  }

  const [handle] = await d
    .select()
    .from(anonymousHandles)
    .where(eq(anonymousHandles.pubkey, pubkey))
    .limit(1);
  if (!handle) {
    return json({ error: "pubkey not registered" }, { status: 404 });
  }
  if (handle.claimedByUserId && handle.claimedByUserId !== user.id) {
    return json(
      { error: "handle already claimed by another user" },
      { status: 409 },
    );
  }
  await d
    .update(anonymousHandles)
    .set({ claimedByUserId: user.id })
    .where(
      and(
        eq(anonymousHandles.id, handle.id),
        isNull(anonymousHandles.claimedByUserId),
      ),
    );

  return json({
    ok: true,
    user: {
      handle: user.handle,
      display_name: user.displayName,
      github_login: user.githubLogin,
    },
    linked_handle: handle.handle,
  });
}
