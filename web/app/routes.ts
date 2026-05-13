import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("workflows", "routes/workflows._index.tsx"),
  route("workflows/:slug", "routes/workflows.$slug.tsx"),
  route("u/:handle", "routes/u.$handle.tsx"),
  route("upload", "routes/upload.tsx"),
  route("settings", "routes/settings.tsx"),
  route("cdn/*", "routes/cdn.$.tsx"),

  // Auth (web)
  route("auth/github/start", "routes/auth.github.start.ts"),
  route("auth/github/callback", "routes/auth.github.callback.ts"),
  route("auth/signout", "routes/auth.signout.ts"),

  // API
  route("api/me", "routes/api.me.ts"),
  route("api/cli/register", "routes/api.cli.register.ts"),
  route("api/workflows", "routes/api.workflows.ts"),
  route("api/workflows/mine", "routes/api.workflows.mine.ts"),
  route("api/workflows/:id/complete", "routes/api.workflows.$id.complete.ts"),
  route("api/workflows/:slug", "routes/api.workflows.$slug.ts"),
  route("api/upload/:token", "routes/api.upload.$token.ts"),
] satisfies RouteConfig;
