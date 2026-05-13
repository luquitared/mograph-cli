import { Link } from "react-router";
import type { Route } from "./+types/packs._index";
import { db } from "../db/client";
import { packs, users } from "../db/schema";
import { and, desc, eq } from "drizzle-orm";
import { getEnv } from "../lib/env";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";

const ALLOWED_KINDS = new Set(["asset", "style"]);

const KIND_LABELS: Record<string, string> = {
  asset: "Asset packs",
  style: "Style packs",
};

const KIND_BLURB: Record<string, string> = {
  asset:
    "Character sheets, voice samples, environment refs — anything a workflow can pull on-demand.",
  style:
    "Source video + extracted frames + style.json: rip the look of a reference clip, reuse on new content.",
};

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Packs — mograf" },
    {
      name: "description",
      content:
        "Reusable asset and style packs: character refs, voice samples, ripped video styles.",
    },
  ];
}

export async function loader({ context, request }: Route.LoaderArgs) {
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const url = new URL(request.url);
  const kindParam = url.searchParams.get("kind");
  const kind = kindParam && ALLOWED_KINDS.has(kindParam) ? kindParam : null;

  const where = kind
    ? and(eq(packs.visibility, "public"), eq(packs.kind, kind))
    : eq(packs.visibility, "public");

  const rows = await d
    .select({
      slug: packs.slug,
      kind: packs.kind,
      title: packs.title,
      summary: packs.summary,
      totalBytes: packs.totalBytes,
      totalFiles: packs.totalFiles,
      createdAt: packs.createdAt,
      handle: users.handle,
      displayName: users.displayName,
    })
    .from(packs)
    .innerJoin(users, eq(packs.ownerUserId, users.id))
    .where(where)
    .orderBy(desc(packs.createdAt));

  return { packs: rows, kind };
}

function formatBytes(n: number | null): string | null {
  if (!n || n <= 0) return null;
  const units = ["B", "KB", "MB", "GB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

export default function PacksIndex({ loaderData }: Route.ComponentProps) {
  const { packs: rows, kind } = loaderData;

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      <SiteNav />

      <main className="mx-auto max-w-6xl px-6 py-16">
        <div className="flex items-baseline justify-between mb-3">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-zinc-500 mb-2">
              Reusable bundles
            </p>
            <h1 className="text-4xl font-medium tracking-tight">Packs</h1>
          </div>
          <div className="text-sm text-zinc-500 hidden sm:block">
            {rows.length} {rows.length === 1 ? "pack" : "packs"}
          </div>
        </div>
        <p className="text-zinc-500 max-w-2xl mb-8">
          Drop-in references workflows can pull on demand. Pull from the CLI:{" "}
          <code className="font-mono text-xs px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-900">
            mograf pack pull &lt;slug&gt;
          </code>
        </p>

        <div className="mb-8 flex items-center gap-2 text-sm">
          <KindTab to="/packs" active={!kind} label="All" />
          <KindTab to="/packs?kind=asset" active={kind === "asset"} label="Asset" />
          <KindTab to="/packs?kind=style" active={kind === "style"} label="Style" />
        </div>

        {rows.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-300 dark:border-zinc-800 p-12 text-center">
            <div className="text-3xl mb-3 font-mono text-zinc-400">∅</div>
            <p className="font-medium mb-1">No packs pushed yet.</p>
            <p className="text-sm text-zinc-500 max-w-md mx-auto">
              Push one from the CLI:{" "}
              <code className="font-mono text-xs px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-900 rounded">
                mograf pack push runs/asset-packs/&lt;name&gt; --kind asset
              </code>
            </p>
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {rows.map((p) => (
              <Link
                key={p.slug}
                to={`/packs/${p.slug}`}
                className="group rounded-xl border border-zinc-200 dark:border-zinc-800 p-5 hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors block"
              >
                <div className="flex items-center justify-between mb-2">
                  <span
                    className={`font-mono text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded ${
                      p.kind === "style"
                        ? "bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400"
                        : "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400"
                    }`}
                  >
                    {p.kind}
                  </span>
                  <span className="text-xs text-zinc-500 font-mono">
                    {p.totalFiles ?? 0} files
                  </span>
                </div>
                <div className="font-medium group-hover:text-fuchsia-600 dark:group-hover:text-fuchsia-400">
                  {p.title}
                </div>
                {p.summary && (
                  <p className="text-sm text-zinc-500 mt-1 line-clamp-2">
                    {p.summary}
                  </p>
                )}
                <div className="mt-4 flex items-center justify-between text-xs text-zinc-500 font-mono">
                  <span>@{p.handle}</span>
                  {formatBytes(p.totalBytes) && (
                    <span>{formatBytes(p.totalBytes)}</span>
                  )}
                </div>
              </Link>
            ))}
          </div>
        )}

        {!kind && rows.length > 0 && (
          <div className="mt-14 grid sm:grid-cols-2 gap-6">
            {(["asset", "style"] as const).map((k) => (
              <div
                key={k}
                className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-5"
              >
                <h2 className="font-medium mb-1">{KIND_LABELS[k]}</h2>
                <p className="text-sm text-zinc-500">{KIND_BLURB[k]}</p>
              </div>
            ))}
          </div>
        )}
      </main>

      <SiteFooter />
    </div>
  );
}

function KindTab({
  to,
  active,
  label,
}: {
  to: string;
  active: boolean;
  label: string;
}) {
  return (
    <Link
      to={to}
      className={
        active
          ? "px-3 py-1.5 rounded-full bg-zinc-900 dark:bg-zinc-100 text-zinc-50 dark:text-zinc-900 font-medium"
          : "px-3 py-1.5 rounded-full border border-zinc-200 dark:border-zinc-800 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
      }
    >
      {label}
    </Link>
  );
}
