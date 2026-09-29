const BASE = "/api/accounts/";

/** Same-origin JSON call. A non-2xx response with a JSON body resolves to
 *  that body (so cards can show its `error`); a network failure or a
 *  non-JSON body rejects. */
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin" };
  if (method !== "GET") {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body ?? {});
  }
  const r = await fetch(BASE + path, init);
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
