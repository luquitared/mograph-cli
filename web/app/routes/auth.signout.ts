import type { Route } from "./+types/auth.signout";
import { clearSessionCookieHeader } from "../lib/session";

export async function action({ request }: Route.ActionArgs) {
  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }
  const url = new URL(request.url);
  const next = url.searchParams.get("next") || "/";
  const headers = new Headers({
    Location: next.startsWith("/") ? next : "/",
  });
  headers.append("Set-Cookie", clearSessionCookieHeader());
  return new Response(null, { status: 303, headers });
}
