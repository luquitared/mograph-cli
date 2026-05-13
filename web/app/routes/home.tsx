import { Link } from "react-router";
import type { Route } from "./+types/home";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "mograf — AI video pipelines, scripted from the CLI" },
    {
      name: "description",
      content:
        "The best AI models for creating videos of every kind. Build, version, share, and remix video pipelines from the command line.",
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

const examples = [
  {
    kind: "narration",
    title: "Narrated explainer",
    body: "TTS + AI visuals, beat-by-beat, aligned to your script.",
  },
  {
    kind: "news",
    title: "News-show clip",
    body: "Recurring anchor, lower-thirds, recurring set, multi-clip consistency.",
  },
  {
    kind: "music",
    title: "Music video",
    body: "Cuts driven by beat detection; per-beat prompts; reusable style.",
  },
  {
    kind: "style-rip",
    title: "Style-rip",
    body: "Sample any reference clip → reusable style pack you can apply.",
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
            AI video, scripted
          </p>
          <h1 className="text-5xl sm:text-6xl md:text-7xl font-medium tracking-tight leading-[1.05]">
            The best AI models
            <br />
            for making
            <span className="relative inline-block ml-3">
              <span className="bg-gradient-to-br from-fuchsia-500 via-violet-500 to-cyan-400 bg-clip-text text-transparent">
                any kind
              </span>
              <span className="absolute -inset-x-2 -bottom-1 h-[2px] bg-gradient-to-r from-fuchsia-500/0 via-fuchsia-500 to-cyan-400/0" />
            </span>
            <br />
            of video.
          </h1>
          <p className="mt-7 max-w-2xl text-lg text-zinc-600 dark:text-zinc-400">
            mograf is a declarative pipeline for AI video. Write a timeline,
            run it from the CLI, render with the strongest model for the job.
            Share the recipe so anyone can re-run it.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link
              to="/workflows"
              className="inline-flex items-center gap-2 rounded-full bg-zinc-900 dark:bg-zinc-100 text-zinc-50 dark:text-zinc-900 px-5 py-2.5 text-sm font-medium hover:opacity-90"
            >
              Browse workflows →
            </Link>
            <a
              href="#install"
              className="inline-flex items-center gap-2 rounded-full border border-zinc-300 dark:border-zinc-700 px-5 py-2.5 text-sm font-medium hover:bg-zinc-50 dark:hover:bg-zinc-900"
            >
              Install the CLI
            </a>
          </div>
        </section>

        <section className="py-14 border-t border-zinc-200 dark:border-zinc-800">
          <div className="flex items-baseline justify-between mb-8">
            <h2 className="text-2xl font-medium tracking-tight">
              Best-of-breed, model-agnostic
            </h2>
            <p className="text-sm text-zinc-500 hidden sm:block">
              Swap models per stage — no lock-in
            </p>
          </div>
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
            Workflows for every kind of video
          </h2>
          <p className="text-zinc-500 max-w-2xl mb-8">
            Each workflow is a recipe: README, a main rendered example, the
            timeline that produced it, plus any reference packs it needs.
            Pushed by the community, runnable in one command.
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            {examples.map((e) => (
              <div
                key={e.kind}
                className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-5 hover:border-zinc-400 dark:hover:border-zinc-600"
              >
                <div className="font-mono text-[10px] uppercase tracking-widest text-zinc-500 mb-2">
                  {e.kind}
                </div>
                <div className="font-medium mb-1">{e.title}</div>
                <div className="text-sm text-zinc-500">{e.body}</div>
              </div>
            ))}
          </div>
        </section>

        <section
          id="install"
          className="py-14 border-t border-zinc-200 dark:border-zinc-800"
        >
          <h2 className="text-2xl font-medium tracking-tight mb-2">
            Push a workflow in one command
          </h2>
          <p className="text-zinc-500 max-w-2xl mb-6">
            Sign in with GitHub, link the CLI on each machine you use, and
            anything you generate locally is one command away from a public,
            re-runnable URL.
          </p>
          <pre className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 p-5 text-sm overflow-x-auto leading-relaxed">
            <code>
              <span className="text-zinc-400"># install the CLI globally (uv recommended; pipx also works)</span>
              {"\n"}uv tool install mograf
              {"\n"}
              {"\n"}<span className="text-zinc-400"># GitHub device flow + register this machine</span>
              {"\n"}mograf login
              {"\n"}
              {"\n"}<span className="text-zinc-400"># publish a pipeline run as a shareable workflow</span>
              {"\n"}mograf publish runs/your-latest-run
            </code>
          </pre>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
