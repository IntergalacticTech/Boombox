// Bearer-token-aware HTTP helpers for the library / playlists / files
// surface. Lives outside the Transport interface because it's HTTP-only
// by design (Phase 2B) and the transport's command/state push pattern
// doesn't fit request/response RPCs over arbitrary endpoints.

import { createContext, useContext, type ReactNode, createElement } from "react";

export interface RemoteApi {
  /** Base URL with trailing slash, e.g. "http://192.168.1.176:8090/". */
  readonly base: string;
  /** GET <base><path> with the bearer token. JSON body, throws on non-2xx. */
  get<T = unknown>(path: string): Promise<T>;
  /** POST <base><path> with JSON body + bearer token. JSON response. */
  post<T = unknown>(path: string, body?: unknown): Promise<T>;
  /** POST multipart upload. `files` is an array of File objects under field
   *  "file". Returns the parsed JSON response. */
  uploadFiles<T = unknown>(path: string, files: File[]): Promise<T>;
}

class HttpApi implements RemoteApi {
  readonly base: string;
  private readonly token: string;

  constructor(base: string, token: string) {
    this.base = base;
    this.token = token;
  }

  private authHeader(): Record<string, string> {
    return { Authorization: `Bearer ${this.token}` };
  }

  async get<T>(path: string): Promise<T> {
    const r = await fetch(this.base + path.replace(/^\//, ""), {
      headers: this.authHeader(),
    });
    if (!r.ok) throw new ApiError(r.status, await r.text());
    return r.json() as Promise<T>;
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const r = await fetch(this.base + path.replace(/^\//, ""), {
      method: "POST",
      headers: {
        ...this.authHeader(),
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) throw new ApiError(r.status, await r.text());
    return r.json() as Promise<T>;
  }

  async uploadFiles<T>(path: string, files: File[]): Promise<T> {
    const form = new FormData();
    for (const f of files) form.append("file", f, f.name);
    const r = await fetch(this.base + path.replace(/^\//, ""), {
      method: "POST",
      headers: this.authHeader(),
      body: form,
    });
    if (!r.ok) throw new ApiError(r.status, await r.text());
    return r.json() as Promise<T>;
  }
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

export function makeApi(base: string, token: string): RemoteApi {
  // base is whatever pairing produced — normalize to a trailing slash so
  // path concatenation works for both "http://host" and "http://host:port".
  return new HttpApi(base.endsWith("/") ? base : base + "/", token);
}

const ApiContext = createContext<RemoteApi | null>(null);

export function ApiProvider(
  { api, children }: { api: RemoteApi; children: ReactNode },
) {
  return createElement(ApiContext.Provider, { value: api }, children);
}

export function useApi(): RemoteApi {
  const ctx = useContext(ApiContext);
  if (!ctx) throw new Error("useApi must be used within an ApiProvider");
  return ctx;
}
