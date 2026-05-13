import type { Route } from "./+types/api.me";
import { db } from "../db/client";
import { cliDevices, users } from "../db/schema";
import { desc, eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { getCurrentSession } from "../lib/session";

const HANDLE_RE = /^[a-z0-9][a-z0-9_-]{1,38}$/;
const RESERVED = new Set([
  "admin", "api", "auth", "cdn", "claim", "settings", "login", "logout",
  "signin", "signout", "upload", "workflows", "u", "me", "new", "edit",
  "anonymous", "system", "mograph", "root",
]);

async function loadMe(d: ReturnType<typeof db>, userId: string) {
  const [user] = await d.select().from(users).where(eq(users.id, userId)).limit(1);
  if (!user) return null;
  const devices = await d
    .select({
      id: cliDevices.id,
      label: cliDevices.label,
      lastUsedAt: cliDevices.lastUsedAt,
      createdAt: cliDevices.createdAt,
    })
    .from(cliDevices)
    .where(eq(cliDevices.userId, user.id))
    .orderBy(desc(cliDevices.lastUsedAt));
  return {
    user: {
      id: user.id,
      handle: user.handle,
      display_name: user.displayName,
      github_login: user.githubLogin,
      avatar_url: user.avatarUrl,
    },
    devices,
  };
}

export async function loader({ context, request }: Route.LoaderArgs) {
  const env = getEnv(context);
  const session = await getCurrentSession(request, env.SESSION_SECRET);
  if (!session) return json({ user: null });
  const me = await loadMe(db(env.DATABASE_URL), session.user_id);
  if (!me) return json({ user: null });
  return json(me);
}

/**
 * PATCH /api/me  { handle: string }
 * Rename your username if the target is free + valid.
 */
export async function action({ context, request }: Route.ActionArgs) {
  if (request.method !== "PATCH" && request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }
  const env = getEnv(context);
  const session = await getCurrentSession(request, env.SESSION_SECRET);
  if (!session) return json({ error: "not signed in" }, { status: 401 });

  const body = (await request.json()) as { handle?: string };
  const desired = (body.handle ?? "").trim().toLowerCase();
  if (!HANDLE_RE.test(desired)) {
    return json(
      {
        error:
          "handle must be 2–39 chars, lowercase letters/digits/hyphens/underscores, starting with a letter or digit",
      },
      { status: 400 },
    );
  }
  if (RESERVED.has(desired)) {
    return json({ error: `'${desired}' is reserved` }, { status: 400 });
  }

  const d = db(env.DATABASE_URL);
  try {
    await d.update(users).set({ handle: desired }).where(eq(users.id, session.user_id));
  } catch (e: any) {
    if (e?.code === "23505") {
      return json({ error: "handle is taken" }, { status: 409 });
    }
    throw e;
  }
  const me = await loadMe(d, session.user_id);
  return json(me);
}
