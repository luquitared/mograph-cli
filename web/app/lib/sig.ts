const MAX_SKEW_S = 300;

export function b64decode(s: string): Uint8Array {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function b64url(bytes: Uint8Array | ArrayBuffer): string {
  const view = bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : bytes;
  let s = "";
  for (let i = 0; i < view.length; i++) s += String.fromCharCode(view[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function toBuf(u: Uint8Array): ArrayBuffer {
  return u.buffer.slice(u.byteOffset, u.byteOffset + u.byteLength) as ArrayBuffer;
}

async function sha256(data: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", toBuf(data)));
}

function hex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Verify an Ed25519-signed request.
 * Signed message: `${method}\n${path}\n${timestamp}\n${hex(sha256(body))}`
 * Headers required: x-mograph-pubkey, x-mograph-timestamp, x-mograph-signature
 */
export async function verifyRequest(
  request: Request,
  bodyBytes: Uint8Array,
): Promise<{ pubkey: string }> {
  const pubkey = request.headers.get("x-mograph-pubkey");
  const ts = request.headers.get("x-mograph-timestamp");
  const sig = request.headers.get("x-mograph-signature");
  if (!pubkey || !ts || !sig) {
    throw new Response("missing signature headers", { status: 401 });
  }

  const tsNum = Number(ts);
  if (!Number.isFinite(tsNum)) {
    throw new Response("bad timestamp", { status: 401 });
  }
  const skew = Math.abs(Math.floor(Date.now() / 1000) - tsNum);
  if (skew > MAX_SKEW_S) {
    throw new Response(`timestamp skew ${skew}s`, { status: 401 });
  }

  const url = new URL(request.url);
  const digest = hex(await sha256(bodyBytes));
  const message = `${request.method}\n${url.pathname}\n${ts}\n${digest}`;
  const messageBytes = new TextEncoder().encode(message);

  const keyBytes = b64decode(pubkey);
  if (keyBytes.length !== 32) {
    throw new Response("bad pubkey length", { status: 401 });
  }

  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    toBuf(keyBytes),
    { name: "Ed25519" },
    false,
    ["verify"],
  );

  const sigBytes = b64decode(sig);
  const ok = await crypto.subtle.verify(
    "Ed25519",
    cryptoKey,
    toBuf(sigBytes),
    toBuf(messageBytes),
  );
  if (!ok) throw new Response("invalid signature", { status: 401 });
  return { pubkey };
}

export async function makeUploadToken(
  secret: string,
  payload: { fileId: string; r2Key: string; bucket: "public" | "private"; expectedSha256?: string; expiresAt: number },
): Promise<string> {
  const body = b64url(new TextEncoder().encode(JSON.stringify(payload)));
  const key = await crypto.subtle.importKey(
    "raw",
    toBuf(new TextEncoder().encode(secret)),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign(
    "HMAC",
    key,
    toBuf(new TextEncoder().encode(body)),
  );
  return `${body}.${b64url(new Uint8Array(sig))}`;
}

export async function verifyUploadToken(
  secret: string,
  token: string,
): Promise<{ fileId: string; r2Key: string; bucket: "public" | "private"; expectedSha256?: string; expiresAt: number }> {
  const [body, sig] = token.split(".");
  if (!body || !sig) throw new Response("bad token", { status: 400 });
  const key = await crypto.subtle.importKey(
    "raw",
    toBuf(new TextEncoder().encode(secret)),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  const ok = await crypto.subtle.verify(
    "HMAC",
    key,
    toBuf(b64decode(sig)),
    toBuf(new TextEncoder().encode(body)),
  );
  if (!ok) throw new Response("invalid token", { status: 401 });
  const payload = JSON.parse(new TextDecoder().decode(b64decode(body)));
  if (payload.expiresAt < Math.floor(Date.now() / 1000)) {
    throw new Response("token expired", { status: 401 });
  }
  return payload;
}
