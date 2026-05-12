const LS_KEY = "mograph:keypair:v1";

function b64(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : bytes;
  let s = "";
  for (let i = 0; i < view.length; i++) s += String.fromCharCode(view[i]);
  return btoa(s);
}

function fromB64(s: string): Uint8Array {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function toBuf(u: Uint8Array): ArrayBuffer {
  return u.buffer.slice(u.byteOffset, u.byteOffset + u.byteLength) as ArrayBuffer;
}

export type Identity = {
  handle: string;
  handleId: string;
  pubkeyB64: string;
  privKey: CryptoKey;
};

type Stored = {
  privPkcs8B64: string;
  pubRawB64: string;
  handle: string;
  handleId: string;
};

async function importPriv(b: Uint8Array): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "pkcs8",
    toBuf(b),
    { name: "Ed25519" },
    true,
    ["sign"],
  );
}

async function ensureRegistered(
  pubkeyB64: string,
): Promise<{ handle: string; handle_id: string }> {
  const r = await fetch("/api/handles", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ pubkey: pubkeyB64 }),
  });
  if (!r.ok) throw new Error(`register failed: ${r.status}`);
  return r.json();
}

export async function loadOrCreateIdentity(): Promise<Identity> {
  const raw = localStorage.getItem(LS_KEY);
  if (raw) {
    const stored = JSON.parse(raw) as Stored;
    const privKey = await importPriv(fromB64(stored.privPkcs8B64));
    return {
      handle: stored.handle,
      handleId: stored.handleId,
      pubkeyB64: stored.pubRawB64,
      privKey,
    };
  }
  const pair = await crypto.subtle.generateKey(
    { name: "Ed25519" },
    true,
    ["sign", "verify"],
  );
  const privPkcs8 = await crypto.subtle.exportKey("pkcs8", pair.privateKey);
  const pubRaw = await crypto.subtle.exportKey("raw", pair.publicKey);
  const pubkeyB64 = b64(pubRaw);
  const reg = await ensureRegistered(pubkeyB64);
  const stored: Stored = {
    privPkcs8B64: b64(privPkcs8),
    pubRawB64: pubkeyB64,
    handle: reg.handle,
    handleId: reg.handle_id,
  };
  localStorage.setItem(LS_KEY, JSON.stringify(stored));
  return {
    handle: reg.handle,
    handleId: reg.handle_id,
    pubkeyB64,
    privKey: pair.privateKey,
  };
}

async function sha256Hex(buf: ArrayBuffer): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(d))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function signedFetch(
  identity: Identity,
  method: "GET" | "POST" | "PUT",
  path: string,
  body?: ArrayBuffer | string,
  contentType?: string,
): Promise<Response> {
  const bytes =
    typeof body === "string"
      ? new TextEncoder().encode(body)
      : body
        ? new Uint8Array(body)
        : new Uint8Array(0);

  const digest = await sha256Hex(toBuf(bytes));
  const ts = Math.floor(Date.now() / 1000).toString();
  const message = `${method}\n${path}\n${ts}\n${digest}`;
  const sig = await crypto.subtle.sign(
    { name: "Ed25519" },
    identity.privKey,
    toBuf(new TextEncoder().encode(message)),
  );

  const headers: Record<string, string> = {
    "X-Mograph-Pubkey": identity.pubkeyB64,
    "X-Mograph-Timestamp": ts,
    "X-Mograph-Signature": b64(sig),
  };
  if (contentType) headers["content-type"] = contentType;

  return fetch(path, {
    method,
    headers,
    body: method === "GET" ? undefined : bytes.byteLength ? toBuf(bytes) : undefined,
  });
}
