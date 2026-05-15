import { describe, it, expect, vi, beforeEach } from "vitest";
import { HttpTransport } from "./HttpTransport";
import type { RemoteState } from "./types";

// Minimal fake WebSocket installed on globalThis.
class FakeWS {
  static instances: FakeWS[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  constructor(url: string) {
    this.url = url;
    FakeWS.instances.push(this);
  }
  close() { this.readyState = 3; }
  // test helpers
  _open() { this.readyState = 1; this.onopen?.(); }
  _msg(obj: unknown) { this.onmessage?.({ data: JSON.stringify(obj) }); }
  _close(code: number) { this.readyState = 3; this.onclose?.({ code }); }
}

const sampleState: RemoteState = {
  boombox: { id: "b", name: "B", version: 1 },
  source: "mopidy", playing: true, track: null,
  art_hash: null, art_url: null, volume: 50, muted: false,
  sources_available: [], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: {},
};

beforeEach(() => {
  FakeWS.instances = [];
  vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket);
});

describe("HttpTransport", () => {
  it("connect() opens a WS with the token in the query string", async () => {
    const t = new HttpTransport("http://pi:8090", "tok123");
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    expect(FakeWS.instances[0].url).toContain("/api/remote/ws?token=tok123");
    expect(t.kind).toBe("http");
  });

  it("onState() receives pushed state", async () => {
    const t = new HttpTransport("http://pi:8090", "tok");
    const seen: RemoteState[] = [];
    t.onState((s) => seen.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    FakeWS.instances[0]._msg({ ok: true, data: sampleState });
    expect(seen).toHaveLength(1);
    expect(seen[0].source).toBe("mopidy");
  });

  it("a 4403 close surfaces status 'disabled'", async () => {
    const t = new HttpTransport("http://pi:8090", "tok");
    const statuses: string[] = [];
    t.onStatus((s) => statuses.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    FakeWS.instances[0]._close(4403);
    expect(statuses).toContain("disabled");
  });

  it("a 4401 close surfaces status 'unauthorized'", async () => {
    const t = new HttpTransport("http://pi:8090", "tok");
    const statuses: string[] = [];
    t.onStatus((s) => statuses.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    FakeWS.instances[0]._close(4401);
    expect(statuses).toContain("unauthorized");
  });

  it("command() POSTs to /api/remote/command with the bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const t = new HttpTransport("http://pi:8090", "tok");
    const res = await t.command("next");
    expect(res).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://pi:8090/api/remote/command",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer tok" }),
      }),
    );
  });

  it("disconnect() does not emit 'error' status", async () => {
    const t = new HttpTransport("http://pi:8090", "tok");
    const statuses: string[] = [];
    t.onStatus((s) => statuses.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    statuses.length = 0;  // ignore the "connected" emission
    t.disconnect();
    FakeWS.instances[0]._close(1000);  // simulate the clean-close that ws.close() triggers
    expect(statuses).not.toContain("error");
  });

  it("a 4503 close surfaces status 'unavailable'", async () => {
    const t = new HttpTransport("http://pi:8090", "tok");
    const statuses: string[] = [];
    t.onStatus((s) => statuses.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    FakeWS.instances[0]._close(4503);
    expect(statuses).toContain("unavailable");
  });

  it("command() returns http_<status> for non-2xx that isn't 401/403", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 502,
      json: async () => { throw new Error("not json"); },
    });
    vi.stubGlobal("fetch", fetchMock);
    const t = new HttpTransport("http://pi:8090", "tok");
    const res = await t.command("next");
    expect(res).toEqual({ ok: false, error: "http_502" });
  });

  it("onState unsubscribe stops the callback", async () => {
    const t = new HttpTransport("http://pi:8090", "tok");
    const seen: RemoteState[] = [];
    const off = t.onState((s) => seen.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    off();
    FakeWS.instances[0]._msg({ ok: true, data: sampleState });
    expect(seen).toHaveLength(0);
  });
});
