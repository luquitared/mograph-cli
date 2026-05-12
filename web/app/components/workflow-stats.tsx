export type WorkflowStats = {
  models?: string[] | null;
  clipCount?: number | null;
  totalDurationS?: number | null;
  totalBytes?: number | null;
};

function fmtDuration(s: number): string {
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m}m ${r}s` : `${m}m`;
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

const MODEL_LABELS: Record<string, string> = {
  "seedance-1.1-pro": "Seedance 1.1",
  "seedance-1-pro": "Seedance",
  "nano-banana-2": "Nano Banana",
  "nano-banana-pro": "Nano Banana Pro",
  "gpt-image-2": "GPT Image 2",
  "gemini-2.5-flash-tts": "Gemini 2.5 TTS",
  "gemini-3.1-flash-tts": "Gemini 3.1 TTS",
  elevenlabs: "ElevenLabs",
  deepgram: "Deepgram",
};

function modelLabel(id: string): string {
  return MODEL_LABELS[id] ?? id;
}

export function WorkflowStatsRow({
  stats,
  size = "md",
}: {
  stats: WorkflowStats;
  size?: "sm" | "md";
}) {
  const chips: { key: string; text: string; tone?: "model" }[] = [];
  if (stats.totalDurationS != null) {
    chips.push({ key: "dur", text: fmtDuration(stats.totalDurationS) });
  }
  if (stats.clipCount != null) {
    chips.push({
      key: "clip",
      text: `${stats.clipCount} clip${stats.clipCount === 1 ? "" : "s"}`,
    });
  }
  if (stats.totalBytes != null) {
    chips.push({ key: "size", text: fmtBytes(stats.totalBytes) });
  }
  if (stats.models && stats.models.length > 0) {
    for (const m of stats.models.slice(0, 3)) {
      chips.push({ key: `m-${m}`, text: modelLabel(m), tone: "model" });
    }
    if (stats.models.length > 3) {
      chips.push({ key: "more", text: `+${stats.models.length - 3}` });
    }
  }
  if (chips.length === 0) return null;

  const base =
    size === "sm"
      ? "text-[10px] px-1.5 py-0.5"
      : "text-xs px-2 py-1";
  return (
    <ul className="flex flex-wrap gap-1.5 font-mono">
      {chips.map((c) => (
        <li
          key={c.key}
          className={`${base} rounded ${
            c.tone === "model"
              ? "bg-fuchsia-500/10 text-fuchsia-700 dark:text-fuchsia-300 border border-fuchsia-500/20"
              : "bg-zinc-100 dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 border border-zinc-200 dark:border-zinc-800"
          }`}
        >
          {c.text}
        </li>
      ))}
    </ul>
  );
}
