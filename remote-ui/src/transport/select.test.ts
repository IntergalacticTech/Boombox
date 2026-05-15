import { describe, it, expect, vi, afterEach } from "vitest";
import { bleAvailable, makeHttpTransport } from "./select";
import { HttpTransport } from "./HttpTransport";

afterEach(() => { vi.unstubAllGlobals(); });

describe("transport selection", () => {
  it("bleAvailable() is false when navigator.bluetooth is absent (iOS)", () => {
    vi.stubGlobal("navigator", {});
    expect(bleAvailable()).toBe(false);
  });

  it("bleAvailable() is true when navigator.bluetooth exists (Android)", () => {
    vi.stubGlobal("navigator", { bluetooth: {} });
    expect(bleAvailable()).toBe(true);
  });

  it("makeHttpTransport() builds an HttpTransport from base + token", () => {
    const t = makeHttpTransport("http://pi:8090", "tok");
    expect(t).toBeInstanceOf(HttpTransport);
    expect(t.kind).toBe("http");
  });
});
