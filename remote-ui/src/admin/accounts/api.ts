import { adminSession } from "../session";

const BASE = "/api/accounts/";

/** Same-origin JSON call with the admin token. A 401 means the admin session
 *  expired (12 h idle, or boombox-setup restarted): drop it so the section
 *  shows the lock screen. A non-2xx response with a JSON body resolves to
 *  that body (cards show its `error`); network failure / non-JSON rejects. */
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = adminSession.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  const init: RequestInit = { method, credentials: "same-origin", headers };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body ?? {});
  }
  const r = await fetch(BASE + path, init);
  if (r.status === 401) adminSession.clear("expired");
  try {
    return (await r.json()) as T;
  } catch {
    throw new Error(`HTTP ${r.status}`);
  }
}

export const accountsApi = {
  get: <T>(path: string) => call<T>("GET", path),
  post: <T>(path: string, body?: unknown) => call<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => call<T>("PUT", path, body),
};
