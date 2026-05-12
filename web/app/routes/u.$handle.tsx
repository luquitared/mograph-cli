import type { Route } from "./+types/u.$handle";
import { db } from "../db/client";
import { anonymousHandles, workflows, workflowVideos } from "../db/schema";
import { and, desc, eq } from "drizzle-orm";
import { getEnv } from "../lib/env";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { WorkflowCard } from "../components/workflow-card";

export function meta({ data }: Route.MetaArgs) {
  if (!data) return [{ title: "Not found — mograph" }];
  return [
    { title: `@${data.handle.handle} — mograph` },
    {
      name: "description",
      content: `Workflows pushed by @${data.handle.handle}.`,
    },
  ];
}

export async function loader({ context, params }: Route.LoaderArgs) {
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const slug = params.handle!;

  const [handle] = await d
    .select()
    .from(anonymousHandles)
    .where(eq(anonymousHandles.handle, slug))
    .limit(1);
  if (!handle) throw new Response("Not Found", { status: 404 });

  const rows = await d
    .select({
      slug: workflows.slug,
      title: workflows.title,
      summary: workflows.summary,
      createdAt: workflows.createdAt,
      handle: anonymousHandles.handle,
      mainVideoKey: workflowVideos.r2Key,
      mainPosterKey: workflowVideos.posterR2Key,
    })
    .from(workflows)
    .innerJoin(
      anonymousHandles,
      eq(workflows.ownerHandleId, anonymousHandles.id),
    )
    .leftJoin(workflowVideos, eq(workflows.mainVideoId, workflowVideos.id))
    .where(
      and(
        eq(workflows.ownerHandleId, handle.id),
        eq(workflows.visibility, "public"),
      ),
    )
    .orderBy(desc(workflows.createdAt));

  return { handle, workflows: rows };
}

export default function Profile({ loaderData }: Route.ComponentProps) {
  const { handle, workflows: rows } = loaderData;

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      <SiteNav />

      <main className="mx-auto max-w-6xl px-6 py-16">
        <div className="flex items-baseline justify-between mb-10">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-zinc-500 mb-2">
              Anonymous handle
            </p>
            <h1 className="text-4xl font-medium tracking-tight font-mono">
              @{handle.handle}
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              {rows.length} {rows.length === 1 ? "workflow" : "workflows"}
              {handle.claimedByUserId ? " · claimed" : ""}
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
