import { useSyncExternalStore } from "react";

/** The admin session token for Admin sections (/api/accounts/*). Kept in
 *  sessionStorage — this tab only, gone when the browser closes — and
 *  mirrored in memory for the React store. */
export const SESSION_KEY = "boombox-admin-session";
const SESSION_URL = "/api/accounts/session";

type Listener = () => void;

function readStored(): string | null {
  try { return sessionStorage.getItem(SESSION_KEY); } catch { return null; }
}

const state: { token: string | null; expired: boolean } = { token: readStored(), expired: false };
const listeners = new Set<Listener>();

function emit(): void {
  for (const l of listeners) l();
}

export const adminSession = {
  token: (): string | null => state.token,
  expired: (): boolean => state.expired,
  subscribe(fn: Listener): () => void {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
  set(token: string): void {
    state.token = token;
    state.expired = false;
    try { sessionStorage.setItem(SESSION_KEY, token); } catch { /* private mode: memory only */ }
    emit();
  },
  clear(reason: "logout" | "expired"): void {
    state.token = null;
    state.expired = reason === "expired";
    try { sessionStorage.removeItem(SESSION_KEY); } catch { /* ignore */ }
    emit();
  },
};

function snapshot(): string {
  return `${state.token ?? ""}|${state.expired ? 1 : 0}`;
}

export function useAdminSession(): { unlocked: boolean; expired: boolean } {
  useSyncExternalStore(adminSession.subscribe, snapshot, snapshot);
  return { unlocked: state.token !== null, expired: state.expired };
}

export type UnlockResult = { ok: true } | { ok: false; error: string };

export async function unlock(password: string): Promise<UnlockResult> {
  let r: Response;
  try {
    r = await fetch(SESSION_URL, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
  } catch {
    return { ok: false, error: "Couldn't reach the Boombox." };
  }
  const body = await r.json().catch(() => ({})) as
    { token?: unknown; error?: unknown; retry_after?: unknown };
  if (r.ok && typeof body.token === "string") {
    adminSession.set(body.token);
    return { ok: true };
  }
  if (r.status === 429) {
    const secs = typeof body.retry_after === "number" ? body.retry_after : 300;
    const mins = Math.max(1, Math.ceil(secs / 60));
    return { ok: false,
      error: `Too many wrong passwords — try again in ${mins} minute${mins === 1 ? "" : "s"}.` };
  }
  if (r.status === 401) return { ok: false, error: "Wrong password." };
  if (r.status === 403) return { ok: false, error: "Admin can't be unlocked from the boombox's own screen." };
  return { ok: false,
    error: typeof body.error === "string" && body.error ? body.error : `Couldn't unlock (HTTP ${r.status}).` };
}

export async function lock(): Promise<void> {
  const token = state.token;
  adminSession.clear("logout");
  if (!token) return;
  try {
    await fetch(SESSION_URL, {
      method: "DELETE", credentials: "same-origin",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: "{}",
    });
  } catch { /* the token dies with its 12 h idle timeout anyway */ }
}
