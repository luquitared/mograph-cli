import type { AppLoadContext } from "react-router";

export function getEnv(context: AppLoadContext) {
  const env = context.cloudflare.env as Env & {
    DATABASE_URL?: string;
  };
  if (!env.DATABASE_URL) {
    throw new Error(
      "DATABASE_URL is not set. Add it to .dev.vars locally or via `wrangler secret put DATABASE_URL` for production.",
    );
  }
  return {
    DATABASE_URL: env.DATABASE_URL,
    R2_PUBLIC: env.R2_PUBLIC,
    R2_PRIVATE: env.R2_PRIVATE,
  };
}
