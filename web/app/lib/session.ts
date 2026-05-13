import { b64decode, b64url } from "./sig";

const COOKIE_NAME = "mograph_session";
const SESSION_TTL_S = 60 * 60 * 24 * 30; // 30 days

export type SessionPayload = {
  user_id: string;
  github_login: string | null;
  exp: number;
};

function toBuf(u: Uint8Array): ArrayBuffer {
  return u.buffer.slice(u.byteOffset, u.byteOffset + u.byteLength) as ArrayBuffer;
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    toBuf(new TextEncoder().encode(secret)),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

export async function signSession(
  secret: string,
  payload: Omit<SessionPayload, "exp"> & { exp?: number },
): Promise<string> {
  const full: SessionPayload = {
    ...payload,
    exp: payload.exp ?? Math.floor(Date.now() / 1000) + SESSION_TTL_S,
  };
  const body = b64url(new TextEncoder().encode(JSON.stringify(full)));
  const key = await hmacKey(secret);
  const sig = await crypto.subtle.sign(
    "HMAC",
    key,
    toBuf(new TextEncoder().encode(body)),
  );
  return `${body}.${b64url(new Uint8Array(sig))}`;
}

export async function verifySession(
  secret: string,
  token: string,
): Promise<SessionPayload | null> {
  const [body, sig] = token.split(".");
  if (!body || !sig) return null;
  try {
    const key = await hmacKey(secret);
    const ok = await crypto.subtle.verify(
      "HMAC",
      key,
      toBuf(b64decode(sig)),
      toBuf(new TextEncoder().encode(body)),
    );
    if (!ok) return null;
    const payload = JSON.parse(
      new TextDecoder().decode(b64decode(body)),
    ) as SessionPayload;
    if (payload.exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch {
    return null;
  }
}

export function readSessionCookie(request: Request): string | null {
  const cookie = request.headers.get("cookie");
  if (!cookie) return null;
  for (const part of cookie.split(/;\s*/)) {
    const [name, ...rest] = part.split("=");
    if (name === COOKIE_NAME) return rest.join("=");
  }
  return null;
}

export function sessionCookieHeader(value: string): string {
  return `${COOKIE_NAME}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_TTL_S}`;
}

export function clearSessionCookieHeader(): string {
  return `${COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`;
}

export async function getCurrentSession(
  request: Request,
  secret: string,
): Promise<SessionPayload | null> {
  const raw = readSessionCookie(request);
  if (!raw) return null;
  return verifySession(secret, raw);
}
