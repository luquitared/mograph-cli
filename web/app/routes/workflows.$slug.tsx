import type { Route } from "./+types/workflows.$slug";
import { db } from "../db/client";
import {
  users,
  workflows,
  workflowVideos,
  workflowFiles,
} from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv } from "../lib/env";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { CopyCommand } from "../components/copy-command";
import { Markdown } from "../components/markdown";
import { WorkflowStatsRow } from "../components/workflow-stats";

export function meta({ data }: Route.MetaArgs) {
  if (!data) return [{ title: "Not found — mograph" }];
  return [
    { title: `${data.workflow.title} — mograf` },
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
      handle: users.handle,
      displayName: users.displayName,
      avatarUrl: users.avatarUrl,
      createdAt: workflows.createdAt,
      models: workflows.models,
      clipCount: workflows.clipCount,
      totalDurationS: workflows.totalDurationS,
      totalBytes: workflows.totalBytes,
    })
    .from(workflows)
    .innerJoin(users, eq(workflows.ownerUserId, users.id))
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
          <a
            href={`/u/${workflow.handle}`}
            className="inline-flex items-center gap-1.5 text-zinc-400 hover:text-zinc-200"
          >
            {workflow.avatarUrl && (
              <img
                src={workflow.avatarUrl}
                alt=""
                className="w-4 h-4 rounded-full"
              />
            )}
            <span>@{workflow.handle}</span>
            {workflow.displayName && (
              <span className="text-zinc-500">· {workflow.displayName}</span>
            )}
          </a>
        </div>
        <h1 className="text-3xl sm:text-4xl font-medium tracking-tight">
          {workflow.title}
        </h1>
        {workflow.summary && (
          <p className="text-lg text-zinc-500 mt-2">{workflow.summary}</p>
        )}
        <div className="mt-4">
          <WorkflowStatsRow stats={workflow} />
        </div>

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

        <div className="mt-6">
          <CopyCommand
            command={`mograf workflow pull ${workflow.slug}`}
          />
          <p className="mt-2 text-xs text-zinc-500">
            Downloads the README, example timeline, and main video into{" "}
            <span className="font-mono">./{workflow.slug}/</span> so you can
            rerun it. Install the CLI first:{" "}
            <code className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-900">
              uv tool install mograf
            </code>
            .
          </p>
        </div>

        <article className="mt-10">
          <Markdown>{workflow.readmeMd}</Markdown>
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
