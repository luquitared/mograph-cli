import { Link } from "react-router";
import type { Route } from "./+types/workflows._index";
import { db } from "../db/client";
import { workflows, anonymousHandles, workflowVideos } from "../db/schema";
import { count, desc, eq } from "drizzle-orm";
import { getEnv } from "../lib/env";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { WorkflowCard } from "../components/workflow-card";

const PAGE_SIZE = 24;

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Workflows — mograph" },
    {
      name: "description",
      content: "Community-pushed video workflows you can run with one command.",
    },
  ];
}

export async function loader({ context, request }: Route.LoaderArgs) {
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const url = new URL(request.url);
  const page = Math.max(1, Number(url.searchParams.get("page") ?? "1") | 0);
  const offset = (page - 1) * PAGE_SIZE;

  const [totalRow] = await d
    .select({ n: count() })
    .from(workflows)
    .where(eq(workflows.visibility, "public"));
  const total = totalRow.n;

  const rows = await d
    .select({
      slug: workflows.slug,
      title: workflows.title,
      summary: workflows.summary,
      createdAt: workflows.createdAt,
      handle: anonymousHandles.handle,
      mainVideoKey: workflowVideos.r2Key,
      mainPosterKey: workflowVideos.posterR2Key,
      models: workflows.models,
      clipCount: workflows.clipCount,
      totalDurationS: workflows.totalDurationS,
      totalBytes: workflows.totalBytes,
    })
    .from(workflows)
    .innerJoin(
      anonymousHandles,
      eq(workflows.ownerHandleId, anonymousHandles.id),
    )
    .leftJoin(workflowVideos, eq(workflows.mainVideoId, workflowVideos.id))
    .where(eq(workflows.visibility, "public"))
    .orderBy(desc(workflows.createdAt))
    .limit(PAGE_SIZE)
    .offset(offset);

  return { workflows: rows, page, total, pageSize: PAGE_SIZE };
}

export default function WorkflowsIndex({ loaderData }: Route.ComponentProps) {
  const { workflows: rows, page, total, pageSize } = loaderData;
  const pages = Math.max(1, Math.ceil(total / pageSize));

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
            {total} {total === 1 ? "workflow" : "workflows"}
          </div>
        </div>

        {rows.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-300 dark:border-zinc-800 p-12 text-center">
            <div className="text-3xl mb-3 font-mono text-zinc-400">∅</div>
            <p className="font-medium mb-1">No workflows pushed yet.</p>
            <p className="text-sm text-zinc-500 max-w-md mx-auto">
              Be the first.{" "}
              <Link to="/upload" className="text-fuchsia-600 dark:text-fuchsia-400 hover:underline">
                Upload one from the browser
              </Link>{" "}
              or from any{" "}
              <code className="font-mono text-xs px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-900 rounded">
                docs/workflows/&lt;name&gt;
              </code>{" "}
              folder run{" "}
              <code className="font-mono text-xs px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-900 rounded">
                mograph workflow push
              </code>
              .
            </p>
          </div>
        ) : (
          <>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {rows.map((w) => (
                <div key={w.slug}>
                  <WorkflowCard workflow={w} showAuthor={false} />
                  <Link
                    to={`/u/${w.handle}`}
                    className="block mt-2 text-xs text-zinc-500 font-mono hover:text-zinc-700 dark:hover:text-zinc-300"
                  >
                    @{w.handle}
                  </Link>
                </div>
              ))}
            </div>

            {pages > 1 && (
              <nav className="mt-10 flex items-center justify-center gap-1 text-sm">
                {page > 1 && (
                  <Link
                    to={`/workflows?page=${page - 1}`}
                    className="px-3 py-1.5 rounded border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-900"
                  >
                    ← prev
                  </Link>
                )}
                <span className="px-3 py-1.5 text-zinc-500 font-mono">
                  {page} / {pages}
                </span>
                {page < pages && (
                  <Link
                    to={`/workflows?page=${page + 1}`}
                    className="px-3 py-1.5 rounded border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-900"
                  >
                    next →
                  </Link>
                )}
              </nav>
            )}
          </>
        )}
      </main>

      <SiteFooter />
    </div>
  );
}
