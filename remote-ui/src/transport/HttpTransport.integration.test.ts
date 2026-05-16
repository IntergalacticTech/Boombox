// Integration tests for HttpTransport.
//
// Distinct from HttpTransport.test.ts in that these exercise multi-step
// flows: reconnect cycles, race conditions, command-after-reconnect.
// FakeWS is still the protocol mock — there's no real network — but the
// scenarios are end-to-end through public API only.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { HttpTransport } from "./HttpTransport";
import type { RemoteState } from "./types";

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
  _open() { this.readyState = 1; this.onopen?.(); }
  _msg(obj: unknown) { this.onmessage?.({ data: JSON.stringify(obj) }); }
  _close(code: number) { this.readyState = 3; this.onclose?.({ code }); }
}

const sampleState: RemoteState = {
  boombox: { id: "b", name: "B", version: 1 },
  source: "mopidy", playing: true, track: null,
  art_hash: null, art_url: null, volume: 0.5, muted: false,
  sources_available: [], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: {},
};

beforeEach(() => {
  FakeWS.instances = [];
  vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket);
});

describe("HttpTransport integration", () => {
  it("end-to-end: connect → state push → close → reconnect → fresh state", async () => {
    vi.useFakeTimers();
    const t = new HttpTransport("http://pi:8090", "tok");
    const states: RemoteState[] = [];
    const statuses: string[] = [];
    t.onState((s) => states.push(s));
    t.onStatus((s) => statuses.push(s));

    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    FakeWS.instances[0]._msg({ ok: true, data: sampleState });
    expect(states.length).toBe(1);

    // Drop the socket (transient close).
    FakeWS.instances[0]._close(1006);
    expect(statuses).toContain("connecting");

    // Reconnect kicks in at 1s.
    vi.advanceTimersByTime(1000);
    expect(FakeWS.instances.length).toBe(2);
    FakeWS.instances[1]._open();
    expect(statuses).toContain("connected");

    // Fresh state push lands.
    FakeWS.instances[1]._msg({
      ok: true, data: { ...sampleState, volume: 0.8 },
    });
    expect(states.length).toBe(2);
    expect(states[1].volume).toBe(0.8);

    vi.useRealTimers();
  });

  it("reconnect backoff cycles 1s → 2s → 4s through repeated failures", async () => {
    vi.useFakeTimers();
    const t = new HttpTransport("http://pi:8090", "tok");
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;

    // Close, retry-attempt-1 also fails, retry-2 also fails.
    FakeWS.instances[0]._close(1006);
    vi.advanceTimersByTime(1000);
    expect(FakeWS.instances.length).toBe(2);
    FakeWS.instances[1]._close(1006);

    vi.advanceTimersByTime(2000);
    expect(FakeWS.instances.length).toBe(3);
    FakeWS.instances[2]._close(1006);

    vi.advanceTimersByTime(4000);
    expect(FakeWS.instances.length).toBe(4);

    vi.useRealTimers();
  });

  it("reconnect counter resets after a successful open", async () => {
    vi.useFakeTimers();
    const t = new HttpTransport("http://pi:8090", "tok");
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;

    // First disconnect → 1s delay → reconnect succeeds → reset.
    FakeWS.instances[0]._close(1006);
    vi.advanceTimersByTime(1000);
    FakeWS.instances[1]._open();

    // Second disconnect should also use the 1s base, not 2s.
    FakeWS.instances[1]._close(1006);
    vi.advanceTimersByTime(999);
    expect(FakeWS.instances.length).toBe(2); // not yet
    vi.advanceTimersByTime(1);
    expect(FakeWS.instances.length).toBe(3); // base delay applied

    vi.useRealTimers();
  });

  it("malformed WS frame is ignored without dropping the connection", async () => {
    const t = new HttpTransport("http://pi:8090", "tok");
    const states: RemoteState[] = [];
    t.onState((s) => states.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;

    // Sneak in a non-JSON frame plus a frame with the wrong shape; then
    // a well-formed one. The good frame should still arrive.
    FakeWS.instances[0].onmessage?.({ data: "not json at all" });
    FakeWS.instances[0]._msg({ ok: false, error: "x" });   // no data
    FakeWS.instances[0]._msg({ ok: true, data: sampleState });
    expect(states.length).toBe(1);
  });

  it("4401 close does not retry and surfaces 'unauthorized'", async () => {
    vi.useFakeTimers();
    const t = new HttpTransport("http://pi:8090", "tok");
    const statuses: string[] = [];
    t.onStatus((s) => statuses.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    FakeWS.instances[0]._close(4401);
    vi.advanceTimersByTime(60_000);
    // Single instance — no reconnect scheduled.
    expect(FakeWS.instances.length).toBe(1);
    expect(statuses).toContain("unauthorized");
    vi.useRealTimers();
  });

  it("command() returns http_5xx without retrying the WS", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 503,
      json: async () => { throw new Error("not json"); },
    });
    vi.stubGlobal("fetch", fetchMock);
    const t = new HttpTransport("http://pi:8090", "tok");
    const res = await t.command("next");
    expect(res).toEqual({ ok: false, error: "http_503" });
  });

  it("multiple onState subscribers all receive a single state push", async () => {
    const t = new HttpTransport("http://pi:8090", "tok");
    const a: RemoteState[] = []; const b: RemoteState[] = [];
    t.onState((s) => a.push(s));
    t.onState((s) => b.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    FakeWS.instances[0]._msg({ ok: true, data: sampleState });
    expect(a.length).toBe(1);
    expect(b.length).toBe(1);
  });

  it("intentional disconnect during reconnect cancels the pending timer", async () => {
    vi.useFakeTimers();
    const t = new HttpTransport("http://pi:8090", "tok");
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    FakeWS.instances[0]._close(1006);    // schedules a retry
    t.disconnect();                       // user navigates away
    vi.advanceTimersByTime(60_000);
    // The pending retry should NOT have created a new instance.
    expect(FakeWS.instances.length).toBe(1);
    vi.useRealTimers();
  });
});
