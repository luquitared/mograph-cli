import type { Route } from "./+types/auth.me";
import { db } from "../db/client";
import { anonymousHandles, users } from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv, json } from "../lib/env";
import { getCurrentSession } from "../lib/session";

export async function loader({ request, context }: Route.LoaderArgs) {
  const env = getEnv(context);
  const session = await getCurrentSession(request, env.SESSION_SECRET);
  if (!session) return json({ user: null });

  const d = db(env.DATABASE_URL);
  const [user] = await d.select().from(users).where(eq(users.id, session.user_id)).limit(1);
  if (!user) return json({ user: null });

  const handles = await d
    .select({
      handle: anonymousHandles.handle,
      id: anonymousHandles.id,
      createdAt: anonymousHandles.createdAt,
    })
    .from(anonymousHandles)
    .where(eq(anonymousHandles.claimedByUserId, user.id));

  return json({
    user: {
      id: user.id,
      handle: user.handle,
      display_name: user.displayName,
      github_login: user.githubLogin,
      avatar_url: user.avatarUrl,
    },
    claimed_handles: handles,
  });
}
