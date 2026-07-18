// Single, centralized client for the /api/setup/* backend.
//
// The wizard runs in two contexts:
//   - Kiosk (localhost): no token — API calls just work.
//   - Phone (LAN): the handoff QR opens .../setup/#t=<TOKEN>. When a token is
//     present in location.hash it is attached to EVERY request as BOTH an
//     `Authorization: Bearer <token>` header AND a `?t=<token>` query param
//     (the server accepts either).
//
// All fetches are same-origin to /api/setup/... — no cross-origin, no base
// host juggling.

import { createContext, useContext, type ReactNode, createElement } from "react";

const BASE = "/api/setup/";

/** Parse the one-time session token out of a URL hash like "#t=TOKEN" (it may
 *  be followed by other `&`-joined fragment params). Returns null when absent
 *  — the kiosk case. */
export function parseHashToken(hash: string): string | null {
  const m = hash.match(/[#&]t=([^&]*)/);
  if (!m || m[1] === "") return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return m[1];
  }
}

export interface SetupApi {
  /** The active session token, or null when none (kiosk, or a phone that
   *  hasn't redeemed the on-screen code yet). */
  readonly token: string | null;
  /** True when running on the device itself (localhost kiosk) — the only
   *  context that may mint a session for the phone-handoff QR, and the one
   *  that never needs a token. */
  readonly isKiosk: boolean;
  /** Adopt a token obtained after load (the typed-URL + code path). */
  adoptToken(token: string): void;
  /** Set by the app: invoked when the server rejects the token, so the UI
   *  can return to code entry. */
  onAuthFail: (() => void) | null;
  get<T = unknown>(path: string): Promise<T>;
  post<T = unknown>(path: string, body?: unknown): Promise<T>;
  put<T = unknown>(path: string, body?: unknown): Promise<T>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: string;
  constructor(status: number, body: string) {
    super(`HTTP ${status}: ${body.slice(0, 200)}`);
    this.status = status;
    this.body = body;
  }
}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

// Survives reloads and stepping away — the server-side session lives 24h and
// is cleared when setup completes, so persisting the bearer locally is safe
// and means the code is entered once, not once per visit.
const TOKEN_STORE_KEY = "boombox-setup-token";

function loadStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORE_KEY);
  } catch {
    return null;
  }
}

function storeToken(token: string | null): void {
  try {
    if (token === null) localStorage.removeItem(TOKEN_STORE_KEY);
    else localStorage.setItem(TOKEN_STORE_KEY, token);
  } catch { /* private mode — the in-memory token still works this visit */ }
}

class HttpSetupApi implements SetupApi {
  token: string | null;
  private readonly hostname: string;
  /** Called when the server rejects our token (expired / service restarted)
   *  so the app can drop back to code entry instead of erroring forever. */
  onAuthFail: (() => void) | null = null;

  constructor(token: string | null, hostname: string) {
    this.token = token;
    this.hostname = hostname;
  }

  get isKiosk(): boolean {
    // Kiosk = running on the device itself. Token presence is NOT the
    // signal — a phone that redeemed the on-screen code has a token but is
    // still a LAN client.
    return LOCAL_HOSTS.has(this.hostname);
  }

  adoptToken(token: string): void {
    this.token = token;
    storeToken(token);
  }

  /** Build the same-origin URL, appending `?t=<token>` when authenticated. */
  private url(path: string): string {
    const url = BASE + path.replace(/^\//, "");
    if (this.token === null) return url;
    const sep = url.includes("?") ? "&" : "?";
    return `${url}${sep}t=${encodeURIComponent(this.token)}`;
  }

  private headers(json: boolean): Record<string, string> {
    const h: Record<string, string> = {};
    if (json) h["Content-Type"] = "application/json";
    if (this.token !== null) h["Authorization"] = `Bearer ${this.token}`;
    return h;
  }

  private async send<T>(method: string, path: string, body?: unknown): Promise<T> {
    const hasBody = body !== undefined;
    const r = await fetch(this.url(path), {
      method,
      headers: this.headers(hasBody),
      body: hasBody ? JSON.stringify(body) : undefined,
    });
    // Our token no longer authorizes (expired, or the setup service
    // restarted and lost the session): forget it and let the app return
    // to code entry rather than failing every action from here on.
    if (r.status === 401 && this.token !== null && !this.isKiosk) {
      this.token = null;
      storeToken(null);
      this.onAuthFail?.();
      throw new ApiError(401, "setup token rejected");
    }
    // The contract returns JSON on both success and validation failures
    // (e.g. 400 { ok:false, error }), so parse the body regardless of status
    // and let callers inspect `ok`. Only a non-JSON error body is fatal.
    const text = await r.text();
    if (!text) {
      if (!r.ok) throw new ApiError(r.status, "");
      return undefined as T;
    }
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new ApiError(r.status, text);
    }
  }

  get<T>(path: string): Promise<T> {
    return this.send<T>("GET", path);
  }

  post<T>(path: string, body?: unknown): Promise<T> {
    return this.send<T>("POST", path, body);
  }

  put<T>(path: string, body?: unknown): Promise<T> {
    return this.send<T>("PUT", path, body);
  }
}

/** Build a client. Token precedence: URL hash (a fresh QR scan wins) → the
 *  stored token from an earlier visit. Pass an explicit hash and hostname
 *  for tests; defaults to the live location. */
export function makeApi(
  hash: string = location.hash,
  hostname: string = location.hostname,
): SetupApi {
  const fromHash = parseHashToken(hash);
  const api = new HttpSetupApi(fromHash ?? loadStoredToken(), hostname);
  if (fromHash !== null) storeToken(fromHash);
  return api;
}

const ApiContext = createContext<SetupApi | null>(null);

export function ApiProvider(
  { api, children }: { api: SetupApi; children: ReactNode },
) {
  return createElement(ApiContext.Provider, { value: api }, children);
}

export function useApi(): SetupApi {
  const ctx = useContext(ApiContext);
  if (!ctx) throw new Error("useApi must be used within an ApiProvider");
  return ctx;
}
