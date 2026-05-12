import { useState } from "react";

export function CopyCommand({
  command,
  label = "Pull this workflow",
}: {
  command: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore — fallback would be a contenteditable trick, not worth it
    }
  }

  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-200 dark:border-zinc-800 text-xs">
        <span className="font-mono uppercase tracking-widest text-zinc-500">
          {label}
        </span>
        <button
          type="button"
          onClick={copy}
          className="font-mono text-xs px-2 py-1 rounded hover:bg-zinc-200 dark:hover:bg-zinc-800 transition-colors text-zinc-600 dark:text-zinc-300"
        >
          {copied ? "✓ copied" : "copy"}
        </button>
      </div>
      <pre className="px-4 py-3 text-sm overflow-x-auto leading-relaxed">
        <code>
          <span className="text-zinc-400 select-none">$ </span>
          {command}
        </code>
      </pre>
    </div>
  );
}
