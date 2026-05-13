import type { Route } from "./+types/packs.$slug";
import { db } from "../db/client";
import { packFiles, packs, users } from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv } from "../lib/env";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { CopyCommand } from "../components/copy-command";
import { Markdown } from "../components/markdown";

const IMG_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif"]);
const VIDEO_EXTS = new Set([".mp4", ".webm", ".mov"]);
const AUDIO_EXTS = new Set([".mp3", ".wav", ".m4a", ".ogg", ".flac"]);

function extOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i).toLowerCase();
}

function kindOf(name: string): "image" | "video" | "audio" | "json" | "md" | "txt" | "other" {
  const e = extOf(name);
  if (IMG_EXTS.has(e)) return "image";
  if (VIDEO_EXTS.has(e)) return "video";
  if (AUDIO_EXTS.has(e)) return "audio";
  if (e === ".json") return "json";
  if (e === ".md") return "md";
  if (e === ".txt") return "txt";
  return "other";
}

function formatBytes(n: number | null): string {
  if (!n || n <= 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

export function meta({ data }: Route.MetaArgs) {
  if (!data) return [{ title: "Not found — mograf" }];
  return [
    { title: `${data.pack.title} — mograf` },
    { name: "description", content: data.pack.summary ?? undefined },
  ];
}

export async function loader({ context, params }: Route.LoaderArgs) {
  const env = getEnv(context);
  const d = db(env.DATABASE_URL);
  const slug = params.slug!;

  const [pk] = await d
    .select({
      id: packs.id,
      slug: packs.slug,
      kind: packs.kind,
      title: packs.title,
      summary: packs.summary,
      readmeMd: packs.readmeMd,
      totalBytes: packs.totalBytes,
      totalFiles: packs.totalFiles,
      createdAt: packs.createdAt,
      handle: users.handle,
      displayName: users.displayName,
      avatarUrl: users.avatarUrl,
    })
    .from(packs)
    .innerJoin(users, eq(packs.ownerUserId, users.id))
    .where(eq(packs.slug, slug))
    .limit(1);

  if (!pk) throw new Response("Not Found", { status: 404 });

  const files = await d
    .select()
    .from(packFiles)
    .where(eq(packFiles.packId, pk.id));

  files.sort((a, b) => a.path.localeCompare(b.path));

  return { pack: pk, files };
}

export default function PackDetail({ loaderData }: Route.ComponentProps) {
  const { pack, files } = loaderData;
  const previews = files
    .map((f) => ({ ...f, kind: kindOf(f.name) }))
    .filter((f) => f.kind === "image" || f.kind === "video");
  const imagePreviews = previews.filter((f) => f.kind === "image").slice(0, 12);
  const videoPreview = previews.find((f) => f.kind === "video");

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      <SiteNav />

      <main className="mx-auto max-w-4xl px-6 py-14">
        <div className="text-sm text-zinc-500 mb-3 font-mono">
          <a href="/packs" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            ← packs
          </a>
          {" / "}
          <a
            href={`/u/${pack.handle}`}
            className="inline-flex items-center gap-1.5 text-zinc-400 hover:text-zinc-200"
          >
            {pack.avatarUrl && (
              <img
                src={pack.avatarUrl}
                alt=""
                className="w-4 h-4 rounded-full"
              />
            )}
            <span>@{pack.handle}</span>
            {pack.displayName && (
              <span className="text-zinc-500">· {pack.displayName}</span>
            )}
          </a>
        </div>

        <div className="flex items-center gap-3 mb-2">
          <span
            className={`font-mono text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded ${
              pack.kind === "style"
                ? "bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400"
                : "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400"
            }`}
          >
            {pack.kind} pack
          </span>
          <span className="text-xs text-zinc-500 font-mono">
            {pack.totalFiles ?? files.length} files · {formatBytes(pack.totalBytes)}
          </span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-medium tracking-tight">
          {pack.title}
        </h1>
        {pack.summary && (
          <p className="text-lg text-zinc-500 mt-2">{pack.summary}</p>
        )}

        {videoPreview && (
          <div className="mt-8 rounded-xl overflow-hidden border border-zinc-200 dark:border-zinc-800">
            <video
              controls
              src={`/cdn/${videoPreview.r2Key}`}
              className="w-full aspect-video bg-black"
            />
          </div>
        )}

        {imagePreviews.length > 0 && (
          <div className="mt-6 grid grid-cols-3 sm:grid-cols-4 gap-2">
            {imagePreviews.map((f) => (
              <a
                key={f.id}
                href={`/cdn/${f.r2Key}`}
                target="_blank"
                rel="noopener noreferrer"
                className="block aspect-square rounded-lg overflow-hidden border border-zinc-200 dark:border-zinc-800 bg-zinc-100 dark:bg-zinc-900"
              >
                <img
                  src={`/cdn/${f.r2Key}`}
                  alt={f.name}
                  loading="lazy"
                  className="w-full h-full object-cover"
                />
              </a>
            ))}
          </div>
        )}

        <div className="mt-6">
          <CopyCommand command={`mograf pack pull ${pack.slug}`} />
          <p className="mt-2 text-xs text-zinc-500">
            Downloads the pack into{" "}
            <span className="font-mono">
              ./runs/{pack.kind === "style" ? "style-packs" : "asset-packs"}/{pack.slug}/
            </span>
            . Install the CLI first:{" "}
            <code className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-900">
              uv tool install mograf
            </code>
            .
          </p>
        </div>

        {pack.readmeMd && (
          <article className="mt-10">
            <Markdown>{pack.readmeMd}</Markdown>
          </article>
        )}

        <section className="mt-10">
          <h2 className="text-sm font-mono uppercase tracking-widest text-zinc-500 mb-3">
            Files
          </h2>
          <ul className="divide-y divide-zinc-200 dark:divide-zinc-800 border border-zinc-200 dark:border-zinc-800 rounded-lg">
            {files.map((f) => (
              <li
                key={f.id}
                className="flex items-center justify-between px-4 py-2.5 text-sm"
              >
                <div className="min-w-0 flex-1 truncate">
                  <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500 mr-3">
                    {kindOf(f.name)}
                  </span>
                  <span className="font-mono">{f.path}</span>
                </div>
                <div className="flex items-center gap-3 ml-3 shrink-0">
                  <span className="text-xs text-zinc-500 font-mono w-16 text-right">
                    {formatBytes(f.sizeBytes)}
                  </span>
                  <a
                    href={`/cdn/${f.r2Key}`}
                    className="text-fuchsia-600 dark:text-fuchsia-400 hover:underline"
                  >
                    download
                  </a>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
