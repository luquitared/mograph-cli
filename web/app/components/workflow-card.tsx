import { Link } from "react-router";
import { WorkflowStatsRow, type WorkflowStats } from "./workflow-stats";

export type WorkflowCardData = {
  slug: string;
  title: string;
  summary: string | null;
  handle: string;
  mainVideoKey: string | null;
  mainPosterKey: string | null;
} & WorkflowStats;

export function WorkflowCard({
  workflow,
  showAuthor = true,
}: {
  workflow: WorkflowCardData;
  showAuthor?: boolean;
}) {
  const w = workflow;
  return (
    <Link
      to={`/workflows/${w.slug}`}
      className="group rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors block"
    >
      <div className="aspect-video bg-zinc-100 dark:bg-zinc-900 relative overflow-hidden">
        {w.mainPosterKey ? (
          <img
            src={`/cdn/${w.mainPosterKey}`}
            alt=""
            className="w-full h-full object-cover"
          />
        ) : w.mainVideoKey ? (
          <video
            src={`/cdn/${w.mainVideoKey}#t=0.1`}
            muted
            playsInline
            preload="metadata"
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 grid place-items-center text-zinc-400 font-mono text-xs">
            no preview
          </div>
        )}
      </div>
      <div className="p-4">
        <div className="font-medium group-hover:text-fuchsia-600 dark:group-hover:text-fuchsia-400">
          {w.title}
        </div>
        {w.summary && (
          <p className="text-sm text-zinc-500 mt-1 line-clamp-2">{w.summary}</p>
        )}
        <div className="mt-3">
          <WorkflowStatsRow stats={w} size="sm" />
        </div>
        {showAuthor && (
          <div className="mt-3 text-xs text-zinc-500 font-mono">@{w.handle}</div>
        )}
      </div>
    </Link>
  );
}
