import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("workflows", "routes/workflows._index.tsx"),
  route("workflows/:slug", "routes/workflows.$slug.tsx"),
  route("upload", "routes/upload.tsx"),
  route("cdn/*", "routes/cdn.$.tsx"),

  // API
  route("api/handles", "routes/api.handles.ts"),
  route("api/workflows", "routes/api.workflows.ts"),
  route("api/workflows/mine", "routes/api.workflows.mine.ts"),
  route("api/workflows/:id/complete", "routes/api.workflows.$id.complete.ts"),
  route("api/workflows/:slug", "routes/api.workflows.$slug.ts"),
  route("api/upload/:token", "routes/api.upload.$token.ts"),
] satisfies RouteConfig;
