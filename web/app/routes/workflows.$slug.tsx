import type { Route } from "./+types/workflows.$slug";
import { db } from "../db/client";
import {
  workflows,
  anonymousHandles,
  workflowVideos,
  workflowFiles,
} from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv } from "../lib/env";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";

export function meta({ data }: Route.MetaArgs) {
  if (!data) return [{ title: "Not found — mograph" }];
  return [
    { title: `${data.workflow.title} — mograph` },
    { name: "description", content: data.workflow.summary ?? undefined },
  ];
}

export async function loader({ context, params }: Route.LoaderArgs) {
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const slug = params.slug!;

  const [wf] = await d
    .select({
      id: workflows.id,
      slug: workflows.slug,
      title: workflows.title,
      summary: workflows.summary,
      readmeMd: workflows.readmeMd,
      mainVideoId: workflows.mainVideoId,
      handle: anonymousHandles.handle,
      createdAt: workflows.createdAt,
    })
    .from(workflows)
    .innerJoin(
      anonymousHandles,
      eq(workflows.ownerHandleId, anonymousHandles.id),
    )
    .where(eq(workflows.slug, slug))
    .limit(1);

  if (!wf) throw new Response("Not Found", { status: 404 });

  const [videos, files] = await Promise.all([
    d.select().from(workflowVideos).where(eq(workflowVideos.workflowId, wf.id)),
    d.select().from(workflowFiles).where(eq(workflowFiles.workflowId, wf.id)),
  ]);

  return { workflow: wf, videos, files };
}

export default function WorkflowDetail({ loaderData }: Route.ComponentProps) {
  const { workflow, videos, files } = loaderData;
  const main = videos.find((v) => v.isMain) ?? videos[0];

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      <SiteNav />

      <main className="mx-auto max-w-4xl px-6 py-14">
        <div className="text-sm text-zinc-500 mb-3 font-mono">
          <a href="/workflows" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            ← workflows
          </a>
          {" / "}
          <span className="text-zinc-400">@{workflow.handle}</span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-medium tracking-tight">
          {workflow.title}
        </h1>
        {workflow.summary && (
          <p className="text-lg text-zinc-500 mt-2">{workflow.summary}</p>
        )}

        {main && (
          <div className="mt-8 rounded-xl overflow-hidden border border-zinc-200 dark:border-zinc-800">
            <video
              controls
              poster={main.posterR2Key ? `/cdn/${main.posterR2Key}` : undefined}
              src={`/cdn/${main.r2Key}`}
              className="w-full aspect-video bg-black"
            />
          </div>
        )}

        <article className="prose prose-zinc dark:prose-invert mt-10 max-w-none whitespace-pre-wrap font-sans">
          {workflow.readmeMd}
        </article>

        {files.length > 0 && (
          <section className="mt-10">
            <h2 className="text-sm font-mono uppercase tracking-widest text-zinc-500 mb-3">
              Files
            </h2>
            <ul className="divide-y divide-zinc-200 dark:divide-zinc-800 border border-zinc-200 dark:border-zinc-800 rounded-lg">
              {files.map((f) => (
                <li key={f.id} className="flex items-center justify-between px-4 py-3 text-sm">
                  <div>
                    <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500 mr-3">
                      {f.kind}
                    </span>
                    <span className="font-medium">{f.name}</span>
                  </div>
                  <a
                    href={`/cdn/${f.r2Key}`}
                    className="text-fuchsia-600 dark:text-fuchsia-400 hover:underline"
                  >
                    download
                  </a>
                </li>
              ))}
            </ul>
          </section>
        )}

        {videos.length > 1 && (
          <section className="mt-10">
            <h2 className="text-sm font-mono uppercase tracking-widest text-zinc-500 mb-3">
              More renders
            </h2>
            <div className="grid sm:grid-cols-2 gap-3">
              {videos
                .filter((v) => !v.isMain)
                .map((v) => (
                  <video
                    key={v.id}
                    controls
                    src={`/cdn/${v.r2Key}`}
                    className="w-full aspect-video bg-black rounded-lg border border-zinc-200 dark:border-zinc-800"
                  />
                ))}
            </div>
          </section>
        )}
      </main>

      <SiteFooter />
    </div>
  );
}
