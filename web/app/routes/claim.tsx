import { useEffect, useState } from "react";
import { Form, Link, useFetcher, useNavigate, useSearchParams } from "react-router";
import type { Route } from "./+types/claim";
import { db } from "../db/client";
import { anonymousHandles, users } from "../db/schema";
import { eq } from "drizzle-orm";
import { getEnv } from "../lib/env";
import { getCurrentSession } from "../lib/session";
import { SiteNav } from "../components/site-nav";
import { SiteFooter } from "../components/site-footer";
import { loadOrCreateIdentity, signedFetch, type Identity } from "../lib/browser-keys";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Claim your handle — mograph" },
    {
      name: "description",
      content:
        "Link your anonymous handles to a real account so they survive across browsers and machines.",
    },
  ];
}

export async function loader({ request, context }: Route.LoaderArgs) {
  const env = getEnv(context);
  const session = await getCurrentSession(request, env.SESSION_SECRET);
  const url = new URL(request.url);
  const prefillCode = url.searchParams.get("code");

  if (!session) {
    return { user: null, claimedHandles: [], prefillCode };
  }
  const d = db(env.DATABASE_URL);
  const [user] = await d
    .select({
      id: users.id,
      handle: users.handle,
      displayName: users.displayName,
      githubLogin: users.githubLogin,
      avatarUrl: users.avatarUrl,
    })
    .from(users)
    .where(eq(users.id, session.user_id))
    .limit(1);
  if (!user) {
    return { user: null, claimedHandles: [], prefillCode };
  }
  const claimedHandles = await d
    .select({
      handle: anonymousHandles.handle,
      id: anonymousHandles.id,
      createdAt: anonymousHandles.createdAt,
    })
    .from(anonymousHandles)
    .where(eq(anonymousHandles.claimedByUserId, user.id));
  return { user, claimedHandles, prefillCode };
}

export default function ClaimPage({ loaderData }: Route.ComponentProps) {
  const { user, claimedHandles, prefillCode } = loaderData;

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      <SiteNav />
      <main className="mx-auto max-w-3xl px-6 py-14">
        <p className="font-mono text-xs uppercase tracking-widest text-zinc-500 mb-2">
          Account
        </p>
        <h1 className="text-4xl font-medium tracking-tight">Claim your handle</h1>
        <p className="mt-3 text-zinc-500 max-w-2xl">
          Anonymous handles live as long as the keypair on your device does.
          Linking them to a GitHub account means you keep them across browsers
          and machines, and your published workflows show up under your real
          name.
        </p>

        {!user ? <SignedOut prefillCode={prefillCode} /> : (
          <SignedIn
            user={user}
            claimedHandles={claimedHandles}
            prefillCode={prefillCode}
          />
        )}
      </main>
      <SiteFooter />
    </div>
  );
}

function SignedOut({ prefillCode }: { prefillCode: string | null }) {
  const nextUrl = prefillCode
    ? `/claim?code=${encodeURIComponent(prefillCode)}`
    : "/claim";
  return (
    <div className="mt-10 rounded-xl border border-zinc-200 dark:border-zinc-800 p-6">
      <h2 className="text-lg font-medium">1. Sign in with GitHub</h2>
      <p className="text-sm text-zinc-500 mt-1">
        We only read your public profile (login, name, avatar) and your
        primary email.
      </p>
      <a
        href={`/auth/github/start?next=${encodeURIComponent(nextUrl)}`}
        className="mt-4 inline-flex items-center gap-2 rounded-full bg-zinc-900 dark:bg-zinc-100 text-zinc-50 dark:text-zinc-900 px-5 py-2.5 text-sm font-medium hover:opacity-90"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
          <path
            fill="currentColor"
            d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.92.58.11.79-.25.79-.55v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.34-1.3-1.7-1.3-1.7-1.06-.72.08-.71.08-.71 1.17.08 1.79 1.2 1.79 1.2 1.04 1.79 2.74 1.27 3.41.97.1-.76.41-1.27.74-1.56-2.55-.29-5.24-1.28-5.24-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.47.11-3.06 0 0 .98-.31 3.2 1.18.93-.26 1.92-.39 2.91-.39s1.98.13 2.91.39c2.22-1.5 3.2-1.18 3.2-1.18.63 1.59.23 2.77.11 3.06.74.81 1.19 1.84 1.19 3.1 0 4.43-2.69 5.41-5.25 5.7.42.36.8 1.07.8 2.16v3.21c0 .31.21.66.8.55C20.21 21.39 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z"
          />
        </svg>
        Sign in with GitHub
      </a>
      {prefillCode && (
        <p className="mt-4 text-sm text-fuchsia-600 dark:text-fuchsia-400">
          Sign in first — we'll bring you back to pair code{" "}
          <span className="font-mono">{prefillCode}</span>.
        </p>
      )}
    </div>
  );
}

function SignedIn({
  user,
  claimedHandles,
  prefillCode,
}: {
  user: { handle: string; displayName: string | null; avatarUrl: string | null; githubLogin: string | null };
  claimedHandles: { handle: string; id: string; createdAt: Date }[];
  prefillCode: string | null;
}) {
  return (
    <div className="mt-10 space-y-6">
      <SignedInHeader user={user} />
      <ClaimThisBrowser claimedHandles={claimedHandles} />
      <PairCli prefillCode={prefillCode} />
      <ClaimedHandlesList handles={claimedHandles} />
    </div>
  );
}

function SignedInHeader({
  user,
}: {
  user: { handle: string; displayName: string | null; avatarUrl: string | null; githubLogin: string | null };
}) {
  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-6 flex items-center gap-4">
      {user.avatarUrl ? (
        <img src={user.avatarUrl} alt="" className="w-12 h-12 rounded-full" />
      ) : (
        <div className="w-12 h-12 rounded-full bg-zinc-200 dark:bg-zinc-800 grid place-items-center font-mono text-sm">
          {user.handle.slice(0, 2)}
        </div>
      )}
      <div className="flex-1 min-w-0">
        <div className="font-medium">{user.displayName ?? user.handle}</div>
        <div className="text-sm text-zinc-500 font-mono">@{user.handle}</div>
      </div>
      {user.githubLogin && (
        <a
          href={`https://github.com/${user.githubLogin}`}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 font-mono"
        >
          github.com/{user.githubLogin}
        </a>
      )}
    </div>
  );
}

type Status = "idle" | "working" | "done" | "error";

function ClaimThisBrowser({
  claimedHandles,
}: {
  claimedHandles: { handle: string }[];
}) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [hadStored, setHadStored] = useState<boolean | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const raw = localStorage.getItem("mograph:keypair:v1");
    setHadStored(!!raw);
    if (!raw) return;
    loadOrCreateIdentity()
      .then(setIdentity)
      .catch((e) => setMessage(`browser keypair error: ${e.message}`));
  }, []);

  const isAlreadyClaimed = identity
    ? claimedHandles.some((h) => h.handle === identity.handle)
    : false;

  async function claim() {
    if (!identity) return;
    setStatus("working");
    setMessage(null);
    try {
      const r = await signedFetch(identity, "POST", "/api/claim/this-browser");
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(`${r.status} ${txt}`);
      }
      setStatus("done");
      setMessage(`@${identity.handle} is now yours.`);
      setTimeout(() => navigate("/claim"), 600);
    } catch (e) {
      setStatus("error");
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-6">
      <h2 className="text-lg font-medium">Claim this browser's handle</h2>
      <p className="text-sm text-zinc-500 mt-1">
        {hadStored === false
          ? "This browser hasn't generated a keypair yet. Visit /upload to create one, then come back."
          : "Links the Ed25519 keypair stored in this browser's localStorage to your account."}
      </p>
      {identity && (
        <div className="mt-3 text-sm font-mono">
          handle: <span className="text-fuchsia-600 dark:text-fuchsia-400">@{identity.handle}</span>
        </div>
      )}
      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          onClick={claim}
          disabled={!identity || status === "working" || isAlreadyClaimed}
          className="inline-flex items-center gap-2 rounded-full bg-fuchsia-600 hover:bg-fuchsia-500 disabled:opacity-50 text-white px-4 py-2 text-sm font-medium"
        >
          {status === "working" ? "Linking…" : isAlreadyClaimed ? "Already linked" : "Link this handle"}
        </button>
        {message && (
          <span
            className={`text-sm ${
              status === "error"
                ? "text-red-600 dark:text-red-400"
                : "text-zinc-500"
            }`}
          >
            {message}
          </span>
        )}
      </div>
    </div>
  );
}

function PairCli({ prefillCode }: { prefillCode: string | null }) {
  const [code, setCode] = useState(prefillCode ?? "");
  const fetcher = useFetcher<{ ok?: boolean; error?: string; handle?: string }>();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const clean = code.trim().toUpperCase();
    if (!clean) return;
    fetcher.submit(
      JSON.stringify({ code: clean }),
      {
        method: "post",
        encType: "application/json",
        action: "/api/claim/confirm",
      },
    );
  }

  const data = fetcher.data;
  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-6">
      <h2 className="text-lg font-medium">Pair a CLI session</h2>
      <p className="text-sm text-zinc-500 mt-1">
        On a machine with the CLI installed, run{" "}
        <code className="font-mono text-xs px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-900">
          mograph claim
        </code>{" "}
        and paste the printed code below.
      </p>
      <form onSubmit={submit} className="mt-4 flex gap-3">
        <input
          type="text"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="A4F7-K2P1"
          className="font-mono uppercase tracking-widest rounded-lg border border-zinc-300 dark:border-zinc-700 bg-transparent px-3 py-2 focus:outline-none focus:border-fuchsia-500 w-44"
          autoFocus={!!prefillCode}
        />
        <button
          type="submit"
          disabled={fetcher.state !== "idle"}
          className="inline-flex items-center gap-2 rounded-full bg-zinc-900 dark:bg-zinc-100 text-zinc-50 dark:text-zinc-900 px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          {fetcher.state === "submitting" ? "Confirming…" : "Confirm"}
        </button>
      </form>
      {data && data.error && (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">{data.error}</p>
      )}
      {data && data.ok && (
        <p className="mt-3 text-sm text-zinc-500">
          ✓ Linked <span className="font-mono">@{data.handle}</span> to your account.
        </p>
      )}
    </div>
  );
}

function ClaimedHandlesList({
  handles,
}: {
  handles: { handle: string; id: string; createdAt: Date }[];
}) {
  if (handles.length === 0) return null;
  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-6">
      <h2 className="text-lg font-medium">Linked handles</h2>
      <ul className="mt-3 divide-y divide-zinc-200 dark:divide-zinc-800">
        {handles.map((h) => (
          <li key={h.id} className="flex items-center justify-between py-2.5 text-sm">
            <span className="font-mono">@{h.handle}</span>
            <Link
              to={`/u/${h.handle}`}
              className="text-zinc-500 hover:text-fuchsia-600 dark:hover:text-fuchsia-400 text-xs"
            >
              workflows →
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
