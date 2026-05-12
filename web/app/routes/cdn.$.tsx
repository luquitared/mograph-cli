import type { Route } from "./+types/cdn.$";
import { getEnv } from "../lib/env";

export async function loader({ context, params }: Route.LoaderArgs) {
  const env = getEnv(context);
  const key = params["*"];
  if (!key) throw new Response("Bad Request", { status: 400 });

  const object = await env.R2_PUBLIC.get(key);
  if (!object) throw new Response("Not Found", { status: 404 });

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("cache-control", "public, max-age=31536000, immutable");

  return new Response(object.body, { headers });
}
