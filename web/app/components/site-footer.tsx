export function SiteFooter() {
  return (
    <footer className="border-t border-zinc-200/70 dark:border-zinc-800/70 mt-24">
      <div className="mx-auto max-w-6xl px-6 py-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 text-xs text-zinc-500">
        <div className="font-mono">mograph · open source video pipeline</div>
        <div className="flex gap-6">
          <a className="hover:text-zinc-900 dark:hover:text-zinc-200" href="/workflows">
            Browse workflows
          </a>
          <a className="hover:text-zinc-900 dark:hover:text-zinc-200" href="https://github.com/" target="_blank" rel="noreferrer">
            Source
          </a>
        </div>
      </div>
    </footer>
  );
}
