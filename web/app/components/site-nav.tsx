import { Link, NavLink } from "react-router";

export function SiteNav() {
  return (
    <header className="border-b border-zinc-200/70 dark:border-zinc-800/70 backdrop-blur sticky top-0 z-30 bg-white/70 dark:bg-zinc-950/70">
      <div className="mx-auto max-w-6xl px-6 h-14 flex items-center justify-between">
        <Link
          to="/"
          className="font-mono text-sm tracking-tight flex items-center gap-2"
        >
          <span className="inline-block w-2 h-2 rounded-full bg-fuchsia-500" />
          mograph
        </Link>
        <nav className="flex items-center gap-6 text-sm">
          <NavLink
            to="/workflows"
            className={({ isActive }) =>
              isActive
                ? "text-zinc-900 dark:text-zinc-50"
                : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
            }
          >
            Workflows
          </NavLink>
          <a
            href="https://github.com/"
            target="_blank"
            rel="noreferrer"
            className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            GitHub
          </a>
        </nav>
      </div>
    </header>
  );
}
