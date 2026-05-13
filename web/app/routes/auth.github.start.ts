import type { Route } from "./+types/auth.github.start";
import { getEnv } from "../lib/env";
import { b64url } from "../lib/sig";

function randomState(): string {
  const buf = new Uint8Array(18);
  crypto.getRandomValues(buf);
  return b64url(buf);
}

function originFor(request: Request, env: ReturnType<typeof getEnv>): string {
  if (env.APP_ORIGIN) return env.APP_ORIGIN.replace(/\/$/, "");
  return new URL(request.url).origin;
}

export async function loader({ request, context }: Route.LoaderArgs) {
  const env = getEnv(context);
  if (!env.GITHUB_CLIENT_ID) {
    return new Response(
      "GITHUB_CLIENT_ID not configured. Set it via `wrangler secret put GITHUB_CLIENT_ID`.",
      { status: 503 },
    );
  }
  const url = new URL(request.url);
  const nextRaw = url.searchParams.get("next") || "/workflows";
  const next = nextRaw.startsWith("/") ? nextRaw : "/workflows";
  const state = randomState();
  const origin = originFor(request, env);
  const callback = `${origin}/auth/github/callback`;

  const authUrl = new URL("https://github.com/login/oauth/authorize");
  authUrl.searchParams.set("client_id", env.GITHUB_CLIENT_ID);
  authUrl.searchParams.set("redirect_uri", callback);
  authUrl.searchParams.set("scope", "read:user user:email");
  authUrl.searchParams.set("state", state);

  const cookieBase = "Path=/auth; HttpOnly; Secure; SameSite=Lax; Max-Age=600";
  const headers = new Headers({ Location: authUrl.toString() });
  headers.append("Set-Cookie", `mograph_oauth_state=${state}; ${cookieBase}`);
  headers.append(
    "Set-Cookie",
    `mograph_oauth_next=${encodeURIComponent(next)}; ${cookieBase}`,
  );
  return new Response(null, { status: 302, headers });
}
