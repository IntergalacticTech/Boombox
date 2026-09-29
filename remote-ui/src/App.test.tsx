import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import App, { apiBase } from "./App";

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("shows the pairing screen when there is no stored pairing", () => {
    render(<App />);
    expect(screen.getByText(/pair with your boombox/i)).toBeTruthy();
  });

  it("shows the remote (not pairing) when a pairing is stored", () => {
    localStorage.setItem("boombox-remote-pairing", JSON.stringify({
      base: "http://pi:8090", token: "t", name: "Kitchen",
    }));
    // Stub WebSocket so TransportProvider's connect() doesn't throw.
    class StubWS {
      onopen: (() => void) | null = null;
      onmessage: unknown = null;
      onclose: unknown = null;
      onerror: unknown = null;
      constructor() { setTimeout(() => this.onopen?.(), 0); }
      close() {}
    }
    vi.stubGlobal("WebSocket", StubWS as unknown as typeof WebSocket);
    render(<App />);
    // The pairing screen's heading must NOT be present.
    expect(screen.queryByText(/pair with your boombox/i)).toBeNull();
  });
});

describe("App shell wiring", () => {
  beforeEach(() => { window.location.hash = ""; });

  it("talks to its own origin outside dev", () => {
    const p = { base: "http://192.168.1.81:8090", token: "t", name: "MarkII" };
    expect(apiBase(p, false)).toBe(window.location.origin);
    expect(apiBase(p, true)).toBe("http://192.168.1.81:8090");
  });

  it("a 401 from any API call shows the re-pair screen", async () => {
    localStorage.setItem("boombox-remote-pairing", JSON.stringify({
      base: "http://pi:8090", token: "t", name: "Kitchen",
    }));
    class StubWS {
      onopen: (() => void) | null = null;
      onmessage: unknown = null; onclose: unknown = null; onerror: unknown = null;
      constructor() { setTimeout(() => this.onopen?.(), 0); }
      close() {}
    }
    vi.stubGlobal("WebSocket", StubWS as unknown as typeof WebSocket);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 401, text: async () => '{"error":"bad_token"}', json: async () => ({}),
    }));
    render(<App />);
    expect(await screen.findByText(/no longer paired/i)).toBeTruthy();
  });
});
