import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import type { Route } from "./+types/upload";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { loadOrCreateIdentity, signedFetch, type Identity } from "../lib/browser-keys";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Share a workflow — mograph" },
    {
      name: "description",
      content:
        "Upload a workflow from your browser. Anonymous-first — a keypair is generated locally and stored in this browser.",
    },
  ];
}

type FileKind = "video" | "timeline" | "md" | "txt";

function classifyFile(name: string): FileKind | null {
  const lower = name.toLowerCase();
  if (/\.(mp4|webm|mov)$/.test(lower)) return "video";
  if (lower.endsWith(".json")) return "timeline";
  if (lower.endsWith(".md")) return "md";
  if (lower.endsWith(".txt")) return "txt";
  return null;
}

function suggestPath(name: string, kind: FileKind): string {
  return `examples/${name}`;
}

async function sha256Hex(buf: ArrayBuffer): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(d))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function coerceDuration(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v) && v >= 0) return v;
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) && n >= 0 ? n : null;
  }
  return null;
}

async function extractTimelineMetadata(
  files: { file: File; kind: FileKind }[],
): Promise<{
  models?: string[];
  clip_count?: number;
  total_duration_s?: number;
}> {
  const timelines = files.filter((s) => s.kind === "timeline");
  if (timelines.length === 0) return {};
  const models = new Set<string>();
  let clipCount = 0;
  const trackTotals: number[] = [];
  for (const t of timelines) {
    let doc: unknown;
    try {
      doc = JSON.parse(await t.file.text());
    } catch {
      continue;
    }
    if (!doc || typeof doc !== "object") continue;
    const d = doc as Record<string, unknown>;
    const defaults =
      typeof d.defaults === "object" && d.defaults
        ? (d.defaults as Record<string, unknown>)
        : {};
    const defaultDur = coerceDuration(defaults.duration);
    const tracks = Array.isArray(d.tracks) ? d.tracks : [];
    let docMax = 0;
    for (const tr of tracks) {
      if (!tr || typeof tr !== "object") continue;
      const clips = Array.isArray((tr as Record<string, unknown>).clips)
        ? ((tr as Record<string, unknown>).clips as unknown[])
        : [];
      let trackDur = 0;
      for (const cl of clips) {
        if (!cl || typeof cl !== "object") continue;
        clipCount += 1;
        const c = cl as Record<string, unknown>;
        if (typeof c.model === "string" && c.model.trim()) {
          models.add(c.model.trim());
        }
        const dur =
          coerceDuration(c.duration) ??
          coerceDuration(c.duration_s) ??
          defaultDur;
        if (dur != null) trackDur += dur;
      }
      docMax = Math.max(docMax, trackDur);
    }
    trackTotals.push(docMax);
  }
  const out: {
    models?: string[];
    clip_count?: number;
    total_duration_s?: number;
  } = {};
  if (models.size) out.models = Array.from(models).sort();
  if (clipCount) out.clip_count = clipCount;
  if (trackTotals.length) {
    const total = Math.max(...trackTotals);
    if (total > 0) out.total_duration_s = Math.round(total);
  }
  return out;
}

type StagedFile = {
  file: File;
  kind: FileKind;
  path: string;
  isMain: boolean;
};

export default function UploadPage() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [identityError, setIdentityError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [readme, setReadme] = useState(
    "# My workflow\n\nDescribe what it does, what models it uses, and how to run it.\n",
  );
  const [staged, setStaged] = useState<StagedFile[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    let mounted = true;
    loadOrCreateIdentity()
      .then((id) => {
        if (mounted) setIdentity(id);
      })
      .catch((e: Error) => {
        if (mounted)
          setIdentityError(
            e.message.includes("Ed25519")
              ? "Your browser doesn't support Ed25519 in WebCrypto. Use Chrome 113+, Safari 17+, or Firefox 130+."
              : `Couldn't set up your handle: ${e.message}`,
          );
      });
    return () => {
      mounted = false;
    };
  }, []);

  function addFiles(list: FileList | null) {
    if (!list) return;
    setStaged((prev) => {
      const next = [...prev];
      for (const file of Array.from(list)) {
        const kind = classifyFile(file.name);
        if (!kind) continue;
        if (next.find((s) => s.file.name === file.name)) continue;
        next.push({
          file,
          kind,
          path: suggestPath(file.name, kind),
          isMain: false,
        });
      }
      const videos = next.filter((s) => s.kind === "video");
      if (videos.length === 1) {
        for (const s of next) s.isMain = s === videos[0];
      } else if (videos.length > 1 && !videos.some((s) => s.isMain)) {
        for (const s of next) s.isMain = s === videos[0];
      }
      return next;
    });
  }

  function removeStaged(name: string) {
    setStaged((prev) => prev.filter((s) => s.file.name !== name));
  }

  function setMain(name: string) {
    setStaged((prev) =>
      prev.map((s) => ({ ...s, isMain: s.file.name === name })),
    );
  }

  function setPath(name: string, newPath: string) {
    setStaged((prev) =>
      prev.map((s) => (s.file.name === name ? { ...s, path: newPath } : s)),
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!identity) return;
    setErrorMsg(null);

    const videos = staged.filter((s) => s.kind === "video");
    if (videos.length === 0) {
      setErrorMsg("Add at least one video (mp4/webm/mov).");
      return;
    }
    if (!videos.some((s) => s.isMain)) {
      setErrorMsg("Mark one video as the main example.");
      return;
    }
    if (!title.trim()) {
      setErrorMsg("Title required.");
      return;
    }

    setSubmitting(true);
    setProgress(["preparing…"]);

    try {
      const manifestFiles = await Promise.all(
        staged.map(async (s) => {
          const buf = await s.file.arrayBuffer();
          const sha = await sha256Hex(buf);
          return {
            name: s.file.name,
            path: s.path,
            kind: s.kind,
            size_bytes: s.file.size,
            sha256: sha,
            ...(s.kind === "video" && s.isMain
              ? { is_main_video: true }
              : {}),
            _buf: buf,
          };
        }),
      );

      const metadata = await extractTimelineMetadata(staged);
      const body = JSON.stringify({
        title: title.trim(),
        summary: summary.trim() || undefined,
        readme_md: readme,
        files: manifestFiles.map(({ _buf, ...rest }) => rest),
        ...(Object.keys(metadata).length ? { metadata } : {}),
      });

      setProgress((p) => [...p, "creating workflow…"]);
      const resp = await signedFetch(
        identity,
        "POST",
        "/api/workflows",
        body,
        "application/json",
      );
      if (!resp.ok) {
        throw new Error(`create failed: ${resp.status} ${await resp.text()}`);
      }
      const info = (await resp.json()) as {
        workflow_id: string;
        slug: string;
        url: string;
        uploads: Array<{
          name: string;
          path: string;
          kind: string;
          upload_url: string;
        }>;
      };

      const bufByPath = new Map(manifestFiles.map((m) => [m.path, m._buf]));
      const ctByKind: Record<string, string> = {
        video: "video/mp4",
        timeline: "application/json",
        md: "text/markdown",
        txt: "text/plain",
      };

      for (const u of info.uploads) {
        const buf = bufByPath.get(u.path);
        if (!buf) continue;
        setProgress((p) => [...p, `uploading ${u.name}…`]);
        const ur = await fetch(u.upload_url, {
          method: "PUT",
          headers: { "content-type": ctByKind[u.kind] ?? "application/octet-stream" },
          body: buf,
        });
        if (!ur.ok) {
          throw new Error(
            `upload ${u.name} failed: ${ur.status} ${await ur.text()}`,
          );
        }
      }

      setProgress((p) => [...p, "finalizing…"]);
      await signedFetch(
        identity,
        "POST",
        `/api/workflows/${info.workflow_id}/complete`,
      );

      setProgress((p) => [...p, `done — opening /${info.slug}`]);
      setTimeout(() => navigate(info.url), 400);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      <SiteNav />

      <main className="mx-auto max-w-3xl px-6 py-14">
        <p className="font-mono text-xs uppercase tracking-widest text-zinc-500 mb-2">
          Share a workflow
        </p>
        <h1 className="text-4xl font-medium tracking-tight">Upload</h1>
        <p className="mt-3 text-zinc-500">
          Drop a README, an example video (the main render), and the timeline
          JSON that produced it. Extra files welcome.
        </p>

        <div className="mt-6 rounded-lg border border-zinc-200 dark:border-zinc-800 px-4 py-3 text-sm flex items-center justify-between gap-4">
          <div>
            <div className="text-xs text-zinc-500 mb-0.5">Posting as</div>
            <div className="font-mono">
              {identity ? `@${identity.handle}` : identityError ? "—" : "…"}
            </div>
          </div>
          <div className="text-xs text-zinc-500 max-w-xs text-right">
            Anonymous handle generated in this browser. Same model as the CLI;
            we'll add a "claim with GitHub" flow soon.
          </div>
        </div>
        {identityError && (
          <p className="mt-3 text-sm text-red-600 dark:text-red-400">{identityError}</p>
        )}

        <form onSubmit={submit} className="mt-10 space-y-6">
          <div>
            <label className="block text-sm font-medium mb-1.5">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              maxLength={200}
              placeholder="Cozy ambient nighttime loop"
              className="w-full rounded-lg border border-zinc-300 dark:border-zinc-700 bg-transparent px-3 py-2 focus:outline-none focus:border-fuchsia-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5">
              Summary <span className="text-zinc-400 font-normal">(one line)</span>
            </label>
            <input
              type="text"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              maxLength={500}
              placeholder="A 4-second looping clip of a desk lamp warming a quiet apartment."
              className="w-full rounded-lg border border-zinc-300 dark:border-zinc-700 bg-transparent px-3 py-2 focus:outline-none focus:border-fuchsia-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5">
              README{" "}
              <span className="text-zinc-400 font-normal">(Markdown)</span>
            </label>
            <textarea
              value={readme}
              onChange={(e) => setReadme(e.target.value)}
              required
              rows={12}
              className="w-full rounded-lg border border-zinc-300 dark:border-zinc-700 bg-transparent px-3 py-2 font-mono text-sm focus:outline-none focus:border-fuchsia-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5">Files</label>
            <div
              className="rounded-lg border-2 border-dashed border-zinc-300 dark:border-zinc-700 px-6 py-8 text-center cursor-pointer hover:border-fuchsia-500/60 transition-colors"
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
              }}
              onDrop={(e) => {
                e.preventDefault();
                addFiles(e.dataTransfer.files);
              }}
            >
              <div className="text-sm text-zinc-500">
                Drop files here or click to pick
              </div>
              <div className="text-xs text-zinc-400 mt-1 font-mono">
                .mp4 / .webm / .mov · .json · .md · .txt
              </div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                hidden
                accept=".mp4,.webm,.mov,.json,.md,.txt"
                onChange={(e) => {
                  addFiles(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>

            {staged.length > 0 && (
              <ul className="mt-3 divide-y divide-zinc-200 dark:divide-zinc-800 border border-zinc-200 dark:border-zinc-800 rounded-lg">
                {staged.map((s) => (
                  <li
                    key={s.file.name}
                    className="px-3 py-2.5 flex items-center gap-3"
                  >
                    <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500 w-16">
                      {s.kind}
                    </span>
                    <input
                      type="text"
                      value={s.path}
                      onChange={(e) => setPath(s.file.name, e.target.value)}
                      className="flex-1 min-w-0 bg-transparent border-b border-transparent hover:border-zinc-300 dark:hover:border-zinc-700 focus:border-fuchsia-500 focus:outline-none font-mono text-sm py-0.5"
                    />
                    <span className="text-xs text-zinc-400 hidden sm:block">
                      {(s.file.size / 1024).toFixed(1)} kB
                    </span>
                    {s.kind === "video" && (
                      <label className="text-xs flex items-center gap-1 cursor-pointer">
                        <input
                          type="radio"
                          name="main"
                          checked={s.isMain}
                          onChange={() => setMain(s.file.name)}
                        />
                        main
                      </label>
                    )}
                    <button
                      type="button"
                      onClick={() => removeStaged(s.file.name)}
                      className="text-zinc-400 hover:text-red-500 text-lg leading-none px-1"
                      aria-label="remove"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {errorMsg && (
            <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-lg p-3">
              {errorMsg}
            </div>
          )}

          {progress.length > 0 && submitting && (
            <ul className="text-sm text-zinc-500 font-mono space-y-0.5">
              {progress.map((p, i) => (
                <li key={i}>· {p}</li>
              ))}
            </ul>
          )}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting || !identity}
              className="inline-flex items-center gap-2 rounded-full bg-zinc-900 dark:bg-zinc-100 text-zinc-50 dark:text-zinc-900 px-5 py-2.5 text-sm font-medium hover:opacity-90 disabled:opacity-50"
            >
              {submitting ? "Publishing…" : "Publish workflow"}
            </button>
            <span className="text-xs text-zinc-500">
              Files upload directly to R2 from your browser.
            </span>
          </div>
        </form>
      </main>

      <SiteFooter />
    </div>
  );
}
