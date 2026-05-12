import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("workflows", "routes/workflows._index.tsx"),
  route("workflows/:slug", "routes/workflows.$slug.tsx"),
  route("cdn/*", "routes/cdn.$.tsx"),
] satisfies RouteConfig;
