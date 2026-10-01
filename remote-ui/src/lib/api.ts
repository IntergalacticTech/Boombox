// Bearer-token-aware HTTP helpers for everything that isn't the state /
// command transport: library, playlists, files, Home Library, video.

import { createContext, useContext, type ReactNode, createElement } from "react";

export interface RemoteApi {
  /** Base URL with trailing slash, e.g. "http://192.168.1.176:8090/". */
  readonly base: string;
  /** GET <base><path> with the bearer token. JSON body, throws on non-2xx. */
  get<T = unknown>(path: string): Promise<T>;
  /** POST <base><path> with JSON body + bearer token. JSON response. */
  post<T = unknown>(path: string, body?: unknown): Promise<T>;
  /** DELETE <base><path> with a JSON body + bearer token. JSON response.
   *  Optional so test doubles needn't implement it. */
  del?<T = unknown>(path: string, body?: unknown): Promise<T>;
  /** POST multipart upload under field "file". Parsed JSON response. */
  uploadFiles<T = unknown>(path: string, files: File[]): Promise<T>;
  /** GET binary (posters, cover art) with the bearer token — <img src> can't
   *  send one. Optional so test doubles needn't implement it. */
  getBlob?(path: string): Promise<Blob>;
}

class HttpApi implements RemoteApi {
  readonly base: string;
  private readonly token: string;
  private readonly onUnauthorized?: () => void;

  constructor(base: string, token: string, onUnauthorized?: () => void) {
    this.base = base;
    this.token = token;
    this.onUnauthorized = onUnauthorized;
  }

  private authHeader(): Record<string, string> {
    return { Authorization: `Bearer ${this.token}` };
  }

  private url(path: string): string {
    return this.base + path.replace(/^\//, "");
  }

  /** 401 = this device's pairing was revoked: tell the app, then throw. */
  private async check(r: Response): Promise<Response> {
    if (r.status === 401) this.onUnauthorized?.();
    if (!r.ok) throw new ApiError(r.status, await r.text());
    return r;
  }

  async get<T>(path: string): Promise<T> {
    const r = await this.check(await fetch(this.url(path), { headers: this.authHeader() }));
    return r.json() as Promise<T>;
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const r = await this.check(await fetch(this.url(path), {
      method: "POST",
      headers: { ...this.authHeader(), "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }));
    return r.json() as Promise<T>;
  }

  async del<T>(path: string, body?: unknown): Promise<T> {
    const r = await this.check(await fetch(this.url(path), {
      method: "DELETE",
      headers: { ...this.authHeader(), "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }));
    return r.json() as Promise<T>;
  }

  async uploadFiles<T>(path: string, files: File[]): Promise<T> {
    const form = new FormData();
    for (const f of files) form.append("file", f, f.name);
    const r = await this.check(await fetch(this.url(path), {
      method: "POST", headers: this.authHeader(), body: form,
    }));
    return r.json() as Promise<T>;
  }

  async getBlob(path: string): Promise<Blob> {
    const r = await this.check(await fetch(this.url(path), { headers: this.authHeader() }));
    return r.blob();
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

export function makeApi(base: string, token: string, onUnauthorized?: () => void): RemoteApi {
  // Normalize to a trailing slash so path concatenation works for both
  // "http://host" and "http://host:port".
  return new HttpApi(base.endsWith("/") ? base : base + "/", token, onUnauthorized);
}

/** A message for the user: the server's JSON `error` when it sent one,
 *  otherwise `fallback` with the status; network failures say so. */
export function apiErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    try {
      const b = JSON.parse(e.body) as { error?: unknown };
      if (typeof b.error === "string" && b.error) return b.error;
    } catch { /* not JSON */ }
    return `${fallback} (HTTP ${e.status})`;
  }
  return "Couldn't reach the boombox.";
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
