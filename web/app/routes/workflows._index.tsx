import { Link } from "react-router";
import type { Route } from "./+types/workflows._index";
import { db } from "../db/client";
import { workflows, anonymousHandles, workflowVideos } from "../db/schema";
import { desc, eq } from "drizzle-orm";
import { getEnv } from "../lib/env";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Workflows — mograph" },
    {
      name: "description",
      content: "Community-pushed video workflows you can run with one command.",
    },
  ];
}

export async function loader({ context }: Route.LoaderArgs) {
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);

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
    .where(eq(workflows.visibility, "public"))
    .orderBy(desc(workflows.createdAt))
    .limit(60);

  return { workflows: rows };
}

export default function WorkflowsIndex({ loaderData }: Route.ComponentProps) {
  const { workflows: rows } = loaderData;

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      <SiteNav />

      <main className="mx-auto max-w-6xl px-6 py-16">
        <div className="flex items-baseline justify-between mb-10">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-zinc-500 mb-2">
              Community recipes
            </p>
            <h1 className="text-4xl font-medium tracking-tight">Workflows</h1>
          </div>
          <div className="text-sm text-zinc-500 hidden sm:block">
            {rows.length} {rows.length === 1 ? "workflow" : "workflows"}
          </div>
        </div>

        {rows.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-300 dark:border-zinc-800 p-12 text-center">
            <div className="text-3xl mb-3 font-mono text-zinc-400">∅</div>
            <p className="font-medium mb-1">No workflows pushed yet.</p>
            <p className="text-sm text-zinc-500 max-w-md mx-auto">
              Be the first. From any{" "}
              <code className="font-mono text-xs px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-900 rounded">
                docs/workflows/&lt;name&gt;
              </code>{" "}
              folder, run{" "}
              <code className="font-mono text-xs px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-900 rounded">
                mograph workflow push
              </code>
              .
            </p>
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {rows.map((w) => (
              <Link
                key={w.slug}
                to={`/workflows/${w.slug}`}
                className="group rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors"
              >
                <div className="aspect-video bg-zinc-100 dark:bg-zinc-900 relative overflow-hidden">
                  {w.mainPosterKey ? (
                    <img
                      src={`/cdn/${w.mainPosterKey}`}
                      alt=""
                      className="w-full h-full object-cover"
                    />
                  ) : w.mainVideoKey ? (
                    <video
                      src={`/cdn/${w.mainVideoKey}#t=0.1`}
                      muted
                      playsInline
                      preload="metadata"
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="absolute inset-0 grid place-items-center text-zinc-400 font-mono text-xs">
                      no preview
                    </div>
                  )}
                </div>
                <div className="p-4">
                  <div className="font-medium group-hover:text-fuchsia-600 dark:group-hover:text-fuchsia-400">
                    {w.title}
                  </div>
                  {w.summary && (
                    <p className="text-sm text-zinc-500 mt-1 line-clamp-2">
                      {w.summary}
                    </p>
                  )}
                  <div className="mt-3 text-xs text-zinc-500 font-mono">
                    @{w.handle}
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>

      <SiteFooter />
    </div>
  );
}
