import { Link } from "react-router";
import type { Route } from "./+types/home";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { CopyCommand } from "../components/copy-command";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "mograf — make videos with Claude Code or Codex" },
    {
      name: "description",
      content:
        "Create videos with Claude Code or Codex. Opinionated, hand-crafted pipelines on the best models available. Share workflows, style packs, and asset packs with the community.",
    },
  ];
}

const models = [
  { name: "Seedance", role: "Video", note: "1.1 Pro · 4-15s clips" },
  { name: "Nano Banana", role: "Image", note: "Gemini 3.1 Flash · Pro" },
  { name: "GPT Image 2", role: "Image", note: "OpenAI · refs + edits" },
  { name: "Gemini 3.1 TTS", role: "Voice", note: "200+ inline audio tags" },
  { name: "ElevenLabs", role: "Voice", note: "forced alignment, clones" },
  { name: "Deepgram", role: "Transcribe", note: "low-latency captions" },
];

const useCases = [
  {
    tag: "Social media",
    title: "Short-form that ships daily",
    body: "Hooks, captions, beat-cut edits — formats tuned for the feed, not the festival.",
  },
  {
    tag: "Educational",
    title: "Explainers that actually explain",
    body: "Narration aligned to your script, AI visuals per beat, consistent characters and sets.",
  },
  {
    tag: "Advertising",
    title: "Product spots on brand",
    body: "Reusable style packs keep every cut on-brand; swap the product, keep the look.",
  },
  {
    tag: "Remix",
    title: "Style-rip anything",
    body: "Sample a reference clip into a reusable style pack, then apply it anywhere.",
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      <SiteNav />

      <main className="mx-auto max-w-6xl px-6">
        <section className="pt-24 pb-20 relative">
          <div className="absolute -top-10 -left-20 size-72 rounded-full bg-fuchsia-500/10 blur-3xl pointer-events-none" />
          <div className="absolute top-10 right-0 size-96 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />
          <p className="font-mono text-xs uppercase tracking-widest text-zinc-500 mb-5">
            AI video, scripted from the CLI
          </p>
          <h1 className="text-5xl sm:text-6xl md:text-7xl font-medium tracking-tight leading-[1.05]">
            Make videos with
            <span className="relative inline-block ml-3">
              <span className="bg-gradient-to-br from-fuchsia-500 via-violet-500 to-cyan-400 bg-clip-text text-transparent">
                Claude Code
              </span>
              <span className="absolute -inset-x-2 -bottom-1 h-[2px] bg-gradient-to-r from-fuchsia-500/0 via-fuchsia-500 to-cyan-400/0" />
            </span>
            <br />
            or Codex.
          </h1>
          <div className="mt-8 max-w-xl">
            <CopyCommand command="uv tool install mograf" label="Install" />
          </div>
          <p className="mt-7 max-w-2xl text-lg text-zinc-600 dark:text-zinc-400">
            Opinionated, hand-crafted pipelines on the best models available —
            built by people who actually make videos with Claude Code and
            Codex. Describe what you want; ship a finished render.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link
              to="/workflows"
              className="inline-flex items-center gap-2 rounded-full bg-zinc-900 dark:bg-zinc-100 text-zinc-50 dark:text-zinc-900 px-5 py-2.5 text-sm font-medium hover:opacity-90"
            >
              Browse workflows →
            </Link>
            <Link
              to="/packs"
              className="inline-flex items-center gap-2 rounded-full border border-zinc-300 dark:border-zinc-700 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50 dark:hover:bg-zinc-900"
            >
              Browse packs
            </Link>
          </div>
        </section>

        <section className="py-14 border-t border-zinc-200 dark:border-zinc-800">
          <div className="flex items-baseline justify-between mb-2">
            <h2 className="text-2xl font-medium tracking-tight">
              The best models, hand-picked
            </h2>
            <p className="text-sm text-zinc-500 hidden sm:block">
              Swap models per stage — no lock-in
            </p>
          </div>
          <p className="text-zinc-500 max-w-2xl mb-8">
            Every stage runs on the strongest model for the job, chosen by
            people who ship video for a living — not whatever was easiest to
            wire up.
          </p>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {models.map((m) => (
              <div
                key={m.name}
                className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-4 hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors"
              >
                <div className="font-mono text-[10px] uppercase tracking-widest text-zinc-500 mb-1">
                  {m.role}
                </div>
                <div className="font-medium">{m.name}</div>
                <div className="text-xs text-zinc-500 mt-0.5">{m.note}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="py-14 border-t border-zinc-200 dark:border-zinc-800">
          <h2 className="text-2xl font-medium tracking-tight mb-2">
            Built for social media, educational content & advertising
          </h2>
          <p className="text-zinc-500 max-w-2xl mb-8">
            Each workflow is a recipe: README, a main rendered example, the
            timeline that produced it, plus any reference packs it needs.
            Pushed by the community, runnable in one command.
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            {useCases.map((u) => (
              <div
                key={u.tag}
                className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-5 hover:border-zinc-400 dark:hover:border-zinc-600"
              >
                <div className="font-mono text-[10px] uppercase tracking-widest text-zinc-500 mb-2">
                  {u.tag}
                </div>
                <div className="font-medium mb-1">{u.title}</div>
                <div className="text-sm text-zinc-500">{u.body}</div>
              </div>
            ))}
          </div>
        </section>

        <section
          id="install"
          className="py-14 border-t border-zinc-200 dark:border-zinc-800"
        >
          <h2 className="text-2xl font-medium tracking-tight mb-2">
            Share workflows, style packs & asset packs
          </h2>
          <p className="text-zinc-500 max-w-2xl mb-6">
            Sign in with GitHub, link the CLI on each machine you use, and
            anything you build locally — a workflow, a style pack, a cast of
            reusable assets — is one command away from a public, re-runnable
            URL the whole community can pull.
          </p>
          <pre className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 p-5 text-sm overflow-x-auto leading-relaxed">
            <code>
              <span className="text-zinc-400"># install the CLI globally (uv recommended; pipx also works)</span>
              {"\n"}uv tool install mograf
              {"\n"}
              {"\n"}<span className="text-zinc-400"># GitHub device flow + register this machine</span>
              {"\n"}mograf login
              {"\n"}
              {"\n"}<span className="text-zinc-400"># publish a workflow, style pack, or asset pack</span>
              {"\n"}mograf publish runs/your-latest-run
            </code>
          </pre>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
