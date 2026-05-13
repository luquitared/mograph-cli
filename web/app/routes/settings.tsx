import { useState } from "react";
import { Link, redirect, useFetcher, useRevalidator } from "react-router";
import type { Route } from "./+types/settings";
import { db } from "../db/client";
import { cliDevices, users } from "../db/schema";
import { desc, eq } from "drizzle-orm";
import { getEnv } from "../lib/env";
import { getCurrentSession } from "../lib/session";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";

export function meta({}: Route.MetaArgs) {
  return [{ title: "Settings — mograph" }];
}

export async function loader({ request, context }: Route.LoaderArgs) {
  const env = getEnv(context);
  const session = await getCurrentSession(request, env.SESSION_SECRET);
  if (!session) return redirect("/auth/github/start?next=/settings");
  const d = db(env.DATABASE_URL);
  const [user] = await d.select().from(users).where(eq(users.id, session.user_id)).limit(1);
  if (!user) return redirect("/auth/github/start?next=/settings");
  const devices = await d
    .select({
      id: cliDevices.id,
      label: cliDevices.label,
      pubkey: cliDevices.pubkey,
      lastUsedAt: cliDevices.lastUsedAt,
      createdAt: cliDevices.createdAt,
    })
    .from(cliDevices)
    .where(eq(cliDevices.userId, user.id))
    .orderBy(desc(cliDevices.lastUsedAt));
  return { user, devices };
}

export default function SettingsPage({ loaderData }: Route.ComponentProps) {
  const { user, devices } = loaderData;
  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      <SiteNav />
      <main className="mx-auto max-w-3xl px-6 py-14 space-y-8">
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-zinc-500 mb-2">
            Account
          </p>
          <h1 className="text-4xl font-medium tracking-tight">Settings</h1>
          <p className="mt-3 text-zinc-500">
            Manage your username and the CLI devices linked to this account.
          </p>
        </div>

        <ProfileCard
          handle={user.handle}
          displayName={user.displayName}
          avatarUrl={user.avatarUrl}
          githubLogin={user.githubLogin}
        />
        <UsernameForm currentHandle={user.handle} />
        <DevicesList devices={devices} />
      </main>
      <SiteFooter />
    </div>
  );
}

function ProfileCard({
  handle,
  displayName,
  avatarUrl,
  githubLogin,
}: {
  handle: string;
  displayName: string | null;
  avatarUrl: string | null;
  githubLogin: string | null;
}) {
  return (
    <section className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-6 flex items-center gap-4">
      {avatarUrl ? (
        <img src={avatarUrl} alt="" className="w-14 h-14 rounded-full" />
      ) : (
        <div className="w-14 h-14 rounded-full bg-zinc-100 dark:bg-zinc-900 grid place-items-center font-mono text-sm">
          {handle.slice(0, 2).toUpperCase()}
        </div>
      )}
      <div className="flex-1 min-w-0">
        <div className="font-medium">{displayName ?? handle}</div>
        <Link
          to={`/u/${handle}`}
          className="text-sm text-zinc-500 font-mono hover:text-fuchsia-600 dark:hover:text-fuchsia-400"
        >
          @{handle}
        </Link>
      </div>
      {githubLogin && (
        <a
          href={`https://github.com/${githubLogin}`}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 font-mono"
        >
          github.com/{githubLogin}
        </a>
      )}
    </section>
  );
}

function UsernameForm({ currentHandle }: { currentHandle: string }) {
  const [value, setValue] = useState(currentHandle);
  const fetcher = useFetcher<{ error?: string; user?: { handle: string } }>();
  const revalidator = useRevalidator();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const desired = value.trim().toLowerCase();
    if (!desired || desired === currentHandle) return;
    fetcher.submit(
      JSON.stringify({ handle: desired }),
      {
        method: "patch",
        encType: "application/json",
        action: "/api/me",
      },
    );
  }

  const data = fetcher.data;
  const success = data && !data.error && data.user;

  // Reload the page data after a successful rename so the nav updates.
  if (success && revalidator.state === "idle" && data.user?.handle !== currentHandle) {
    revalidator.revalidate();
  }

  return (
    <section className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-6">
      <h2 className="text-lg font-medium">Username</h2>
      <p className="text-sm text-zinc-500 mt-1">
        Your profile lives at{" "}
        <span className="font-mono">mograph.dev/u/&lt;username&gt;</span>. Pick
        any unclaimed name — lowercase letters/digits/hyphens/underscores, 2–39
        chars.
      </p>
      <form onSubmit={submit} className="mt-4 flex gap-3">
        <span className="text-zinc-500 font-mono self-center">@</span>
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value.toLowerCase())}
          className="font-mono rounded-lg border border-zinc-300 dark:border-zinc-700 bg-transparent px-3 py-2 focus:outline-none focus:border-fuchsia-500 w-64"
        />
        <button
          type="submit"
          disabled={fetcher.state !== "idle" || value.trim() === currentHandle}
          className="inline-flex items-center gap-2 rounded-full bg-zinc-900 dark:bg-zinc-100 text-zinc-50 dark:text-zinc-900 px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          {fetcher.state === "submitting" ? "Saving…" : "Save"}
        </button>
      </form>
      {data?.error && (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">{data.error}</p>
      )}
      {success && (
        <p className="mt-3 text-sm text-zinc-500">
          ✓ Now <span className="font-mono">@{data.user!.handle}</span>.
        </p>
      )}
    </section>
  );
}

function DevicesList({
  devices,
}: {
  devices: {
    id: string;
    label: string | null;
    pubkey: string;
    lastUsedAt: Date | null;
    createdAt: Date;
  }[];
}) {
  return (
    <section className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-6">
      <h2 className="text-lg font-medium">Linked CLI devices</h2>
      <p className="text-sm text-zinc-500 mt-1">
        Each <span className="font-mono">mograph login</span> on a new machine
        adds a row here. The keypair never leaves the device.
      </p>
      {devices.length === 0 ? (
        <p className="mt-4 text-sm text-zinc-500">
          No devices yet. Run{" "}
          <code className="font-mono text-xs px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-900">
            python scripts/mograph.py login
          </code>{" "}
          on your laptop to link one.
        </p>
      ) : (
        <ul className="mt-4 divide-y divide-zinc-200 dark:divide-zinc-800">
          {devices.map((d) => (
            <li key={d.id} className="py-3 flex items-center justify-between text-sm">
              <div className="min-w-0">
                <div className="font-medium">
                  {d.label ?? <span className="text-zinc-500">untitled</span>}
                </div>
                <div className="text-xs text-zinc-500 font-mono truncate">
                  {d.pubkey.slice(0, 14)}…{d.pubkey.slice(-10)}
                </div>
              </div>
              <div className="text-xs text-zinc-500 text-right">
                {d.lastUsedAt
                  ? `used ${new Date(d.lastUsedAt).toLocaleDateString()}`
                  : "never used"}
                <br />
                <span className="text-[10px]">
                  added {new Date(d.createdAt).toLocaleDateString()}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
