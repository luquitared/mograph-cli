import type { AppLoadContext } from "react-router";

export function getEnv(context: AppLoadContext) {
  const env = context.cloudflare.env as Env & {
    DATABASE_URL?: string;
    UPLOAD_SECRET?: string;
    SESSION_SECRET?: string;
    GITHUB_CLIENT_ID?: string;
    GITHUB_CLIENT_SECRET?: string;
    APP_ORIGIN?: string;
  };
  if (!env.DATABASE_URL) {
    throw new Error(
      "DATABASE_URL is not set. Add it to .dev.vars locally or via `wrangler secret put DATABASE_URL` for production.",
    );
  }
  if (!env.UPLOAD_SECRET) {
    throw new Error(
      "UPLOAD_SECRET is not set. Add it to .dev.vars locally or via `wrangler secret put UPLOAD_SECRET` for production.",
    );
  }
  return {
    DATABASE_URL: env.DATABASE_URL,
    UPLOAD_SECRET: env.UPLOAD_SECRET,
    SESSION_SECRET: env.SESSION_SECRET ?? env.UPLOAD_SECRET,
    GITHUB_CLIENT_ID: env.GITHUB_CLIENT_ID ?? null,
    GITHUB_CLIENT_SECRET: env.GITHUB_CLIENT_SECRET ?? null,
    APP_ORIGIN: env.APP_ORIGIN ?? null,
    R2_PUBLIC: env.R2_PUBLIC,
    R2_PRIVATE: env.R2_PRIVATE,
  };
}

export function json<T>(data: T, init?: ResponseInit): Response {
  return new Response(JSON.stringify(data), {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
}
