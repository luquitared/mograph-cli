import type { Route } from "./+types/api.cli.register";
import { db } from "../db/client";
import { cliDevices, users } from "../db/schema";
import { eq } from "drizzle-orm";
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
 * POST /api/cli/register
 * Body: { github_access_token: string, label?: string }
 * Signed by the CLI's Ed25519 keypair.
 *
 * Atomic device-flow completion: server verifies the GitHub token, upserts
 * the user, and binds the CLI's pubkey to that user in cli_devices.
 * Idempotent — re-running on the same machine just refreshes the row.
 */
export async function action({ context, request }: Route.ActionArgs) {
  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const bodyBytes = new Uint8Array(await request.arrayBuffer());
  const { pubkey } = await verifyRequest(request, bodyBytes);

  let body: { github_access_token?: string; label?: string };
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

  // Upsert the device row by pubkey.
  const [existingDevice] = await d
    .select()
    .from(cliDevices)
    .where(eq(cliDevices.pubkey, pubkey))
    .limit(1);
  if (existingDevice) {
    if (existingDevice.userId !== user.id) {
      return json(
        { error: "pubkey already bound to another account" },
        { status: 409 },
      );
    }
    await d
      .update(cliDevices)
      .set({
        label: body.label ?? existingDevice.label,
        lastUsedAt: new Date(),
      })
      .where(eq(cliDevices.id, existingDevice.id));
  } else {
    await d.insert(cliDevices).values({
      userId: user.id,
      pubkey,
      label: body.label ?? null,
      lastUsedAt: new Date(),
    });
  }

  return json({
    ok: true,
    user: {
      id: user.id,
      handle: user.handle,
      display_name: user.displayName,
      github_login: user.githubLogin,
      avatar_url: user.avatarUrl,
    },
  });
}
