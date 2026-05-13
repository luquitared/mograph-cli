import { Form, Link, NavLink, useRouteLoaderData } from "react-router";

type RootData = {
  user: {
    handle: string;
    displayName: string | null;
    avatarUrl: string | null;
    githubLogin: string | null;
  } | null;
};

export function SiteNav() {
  const root = useRouteLoaderData("root") as RootData | undefined;
  const user = root?.user ?? null;

  return (
    <header className="border-b border-zinc-200/70 dark:border-zinc-800/70 backdrop-blur sticky top-0 z-30 bg-white/70 dark:bg-zinc-950/70">
      <div className="mx-auto max-w-6xl px-6 h-14 flex items-center justify-between">
        <Link
          to="/"
          className="font-mono text-sm tracking-tight flex items-center gap-2"
        >
          <span className="inline-block w-2 h-2 rounded-full bg-fuchsia-500" />
          mograf
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
          <NavLink
            to="/packs"
            className={({ isActive }) =>
              isActive
                ? "text-zinc-900 dark:text-zinc-50"
                : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
            }
          >
            Packs
          </NavLink>
          <NavLink
            to="/upload"
            className={({ isActive }) =>
              isActive
                ? "text-zinc-900 dark:text-zinc-50"
                : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
            }
          >
            Share
          </NavLink>
          {user ? (
            <div className="flex items-center gap-3 pl-2 border-l border-zinc-200 dark:border-zinc-800">
              <Link
                to={`/u/${user.handle}`}
                className="flex items-center gap-2 text-zinc-700 dark:text-zinc-200 hover:text-zinc-900 dark:hover:text-white"
                title="Your workflows"
              >
                {user.avatarUrl ? (
                  <img
                    src={user.avatarUrl}
                    alt=""
                    className="w-6 h-6 rounded-full"
                  />
                ) : (
                  <span className="w-6 h-6 rounded-full bg-zinc-200 dark:bg-zinc-800 grid place-items-center font-mono text-[10px]">
                    {user.handle.slice(0, 2)}
                  </span>
                )}
                <span className="hidden sm:inline">@{user.handle}</span>
              </Link>
              <Link
                to="/settings"
                className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 text-xs"
              >
                settings
              </Link>
              <Form method="post" action="/auth/signout">
                <button
                  type="submit"
                  className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 text-xs"
                >
                  sign out
                </button>
              </Form>
            </div>
          ) : (
            <Link
              to="/auth/github/start?next=/workflows"
              reloadDocument
              className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
            >
              Sign in
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}
