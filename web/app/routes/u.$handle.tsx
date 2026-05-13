import type { Route } from "./+types/u.$handle";
import { db } from "../db/client";
import { users, workflows, workflowVideos } from "../db/schema";
import { and, desc, eq } from "drizzle-orm";
import { getEnv } from "../lib/env";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { WorkflowCard } from "../components/workflow-card";

export function meta({ data }: Route.MetaArgs) {
  if (!data) return [{ title: "Not found — mograph" }];
  return [
    { title: `@${data.user.handle} — mograph` },
    {
      name: "description",
      content: `Workflows pushed by @${data.user.handle}.`,
    },
  ];
}

export async function loader({ context, params }: Route.LoaderArgs) {
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const handle = params.handle!.toLowerCase();

  const [user] = await d
    .select({
      id: users.id,
      handle: users.handle,
      displayName: users.displayName,
      githubLogin: users.githubLogin,
      avatarUrl: users.avatarUrl,
      createdAt: users.createdAt,
    })
    .from(users)
    .where(eq(users.handle, handle))
    .limit(1);
  if (!user) throw new Response("Not Found", { status: 404 });

  const rows = await d
    .select({
      slug: workflows.slug,
      title: workflows.title,
      summary: workflows.summary,
      createdAt: workflows.createdAt,
      handle: users.handle,
      mainVideoKey: workflowVideos.r2Key,
      mainPosterKey: workflowVideos.posterR2Key,
      models: workflows.models,
      clipCount: workflows.clipCount,
      totalDurationS: workflows.totalDurationS,
      totalBytes: workflows.totalBytes,
    })
    .from(workflows)
    .innerJoin(users, eq(workflows.ownerUserId, users.id))
    .leftJoin(workflowVideos, eq(workflows.mainVideoId, workflowVideos.id))
    .where(
      and(
        eq(workflows.ownerUserId, user.id),
        eq(workflows.visibility, "public"),
      ),
    )
    .orderBy(desc(workflows.createdAt));

  return { user, workflows: rows };
}

export default function Profile({ loaderData }: Route.ComponentProps) {
  const { user, workflows: rows } = loaderData;

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      <SiteNav />

      <main className="mx-auto max-w-6xl px-6 py-16">
        <div className="flex items-start gap-5 mb-10">
          {user.avatarUrl ? (
            <img
              src={user.avatarUrl}
              alt=""
              className="w-16 h-16 rounded-full border border-zinc-200 dark:border-zinc-800"
            />
          ) : (
            <div className="w-16 h-16 rounded-full bg-zinc-100 dark:bg-zinc-900 grid place-items-center font-mono text-xs">
              {user.handle.slice(0, 2).toUpperCase()}
            </div>
          )}
          <div className="flex-1 min-w-0">
            <p className="font-mono text-xs uppercase tracking-widest text-zinc-500">
              Profile
            </p>
            <h1 className="text-3xl font-medium tracking-tight">
              {user.displayName ?? `@${user.handle}`}
            </h1>
            <div className="mt-1 text-sm text-zinc-500 font-mono">
              @{user.handle}
              {user.githubLogin && (
                <>
                  {" · "}
                  <a
                    href={`https://github.com/${user.githubLogin}`}
                    target="_blank"
                    rel="noreferrer"
                    className="hover:text-zinc-900 dark:hover:text-zinc-100"
                  >
                    github.com/{user.githubLogin}
                  </a>
                </>
              )}
            </div>
            <p className="text-sm text-zinc-500 mt-2">
              {rows.length} {rows.length === 1 ? "workflow" : "workflows"}
            </p>
          </div>
        </div>

        {rows.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-300 dark:border-zinc-800 p-12 text-center">
            <p className="text-sm text-zinc-500">No workflows yet.</p>
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {rows.map((w) => (
              <WorkflowCard key={w.slug} workflow={w} showAuthor={false} />
            ))}
          </div>
        )}
      </main>

      <SiteFooter />
    </div>
  );
}
