import type { Route } from "./+types/auth.github.callback";
import { db } from "../db/client";
import { users } from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv } from "../lib/env";
import { sessionCookieHeader, signSession } from "../lib/session";

function readCookie(request: Request, name: string): string | null {
  const c = request.headers.get("cookie");
  if (!c) return null;
  for (const part of c.split(/;\s*/)) {
    const [k, ...rest] = part.split("=");
    if (k === name) return rest.join("=");
  }
  return null;
}

function originFor(request: Request, env: ReturnType<typeof getEnv>): string {
  if (env.APP_ORIGIN) return env.APP_ORIGIN.replace(/\/$/, "");
  return new URL(request.url).origin;
}

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

export async function loader({ request, context }: Route.LoaderArgs) {
  const env = getEnv(context);
  if (!env.GITHUB_CLIENT_ID || !env.GITHUB_CLIENT_SECRET) {
    return new Response("GitHub OAuth not configured", { status: 503 });
  }

  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  if (!code || !state) return new Response("missing code/state", { status: 400 });

  const cookieState = readCookie(request, "mograph_oauth_state");
  const cookieNext = readCookie(request, "mograph_oauth_next");
  if (!cookieState || cookieState !== state) {
    return new Response("state mismatch", { status: 400 });
  }
  const next = cookieNext ? decodeURIComponent(cookieNext) : "/claim";
  const safeNext = next.startsWith("/") ? next : "/claim";

  // Exchange code for access token.
  const tokenResp = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify({
      client_id: env.GITHUB_CLIENT_ID,
      client_secret: env.GITHUB_CLIENT_SECRET,
      code,
      redirect_uri: `${originFor(request, env)}/auth/github/callback`,
    }),
  });
  if (!tokenResp.ok) {
    return new Response(`token exchange failed: ${tokenResp.status}`, {
      status: 502,
    });
  }
  const tokenJson = (await tokenResp.json()) as {
    access_token?: string;
    error?: string;
  };
  if (!tokenJson.access_token) {
    return new Response(`oauth error: ${tokenJson.error ?? "no token"}`, {
      status: 401,
    });
  }

  // Fetch GitHub user.
  const userResp = await fetch("https://api.github.com/user", {
    headers: {
      authorization: `Bearer ${tokenJson.access_token}`,
      "user-agent": "mograph",
      accept: "application/vnd.github+json",
    },
  });
  if (!userResp.ok) {
    return new Response(`github /user failed: ${userResp.status}`, {
      status: 502,
    });
  }
  const ghUser = (await userResp.json()) as {
    id: number;
    login: string;
    name?: string | null;
    email?: string | null;
    avatar_url?: string | null;
  };
  const githubId = String(ghUser.id);

  // If email isn't public, fetch primary verified email.
  let email = ghUser.email ?? null;
  if (!email) {
    try {
      const emailsResp = await fetch("https://api.github.com/user/emails", {
        headers: {
          authorization: `Bearer ${tokenJson.access_token}`,
          "user-agent": "mograph",
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
  let [existing] = await d
    .select()
    .from(users)
    .where(eq(users.githubId, githubId))
    .limit(1);

  if (!existing) {
    const handle = await makeHandleFromGithub(d, ghUser.login);
    [existing] = await d
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
    // Refresh display fields opportunistically.
    [existing] = await d
      .update(users)
      .set({
        email: email ?? existing.email,
        githubLogin: ghUser.login,
        displayName: ghUser.name ?? existing.displayName,
        avatarUrl: ghUser.avatar_url ?? existing.avatarUrl,
      })
      .where(eq(users.id, existing.id))
      .returning();
  }

  const sessionToken = await signSession(env.SESSION_SECRET, {
    user_id: existing.id,
    github_login: existing.githubLogin ?? null,
  });

  const headers = new Headers({ Location: safeNext });
  headers.append("Set-Cookie", sessionCookieHeader(sessionToken));
  headers.append("Set-Cookie", "mograph_oauth_state=; Path=/auth; Max-Age=0");
  headers.append("Set-Cookie", "mograph_oauth_next=; Path=/auth; Max-Age=0");
  return new Response(null, { status: 302, headers });
}
