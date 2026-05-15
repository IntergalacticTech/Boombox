import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";

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
