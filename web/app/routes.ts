import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("workflows", "routes/workflows._index.tsx"),
  route("workflows/:slug", "routes/workflows.$slug.tsx"),
  route("u/:handle", "routes/u.$handle.tsx"),
  route("upload", "routes/upload.tsx"),
  route("claim", "routes/claim.tsx"),
  route("cdn/*", "routes/cdn.$.tsx"),

  // Auth
  route("auth/github/start", "routes/auth.github.start.ts"),
  route("auth/github/callback", "routes/auth.github.callback.ts"),
  route("auth/signout", "routes/auth.signout.ts"),
  route("auth/me", "routes/auth.me.ts"),

  // Claim API
  route("api/claim/start", "routes/api.claim.start.ts"),
  route("api/claim/status", "routes/api.claim.status.ts"),
  route("api/claim/confirm", "routes/api.claim.confirm.ts"),
  route("api/claim/this-browser", "routes/api.claim.this-browser.ts"),
  route("api/claim/cli-direct", "routes/api.claim.cli-direct.ts"),

  // API
  route("api/handles", "routes/api.handles.ts"),
  route("api/workflows", "routes/api.workflows.ts"),
  route("api/workflows/mine", "routes/api.workflows.mine.ts"),
  route("api/workflows/:id/complete", "routes/api.workflows.$id.complete.ts"),
  route("api/workflows/:slug", "routes/api.workflows.$slug.ts"),
  route("api/upload/:token", "routes/api.upload.$token.ts"),
] satisfies RouteConfig;
