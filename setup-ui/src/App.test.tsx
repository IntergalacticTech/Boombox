import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import App from "./App";

const STATUS = {
  service_version: "1.0.0",
  complete: false,
  identity: { name: "Boombox", id: "bb-1", hostname: "boombox.local" },
  wifi: { present: false, connected: false, ssid: "", ip: "" },
  music: { url: "", username: "", configured: false, reachable: false },
  video: { mode: "builtin", base: "", has_key: false },
  remote: { enabled: false, peers: [] },
  skin: null,
};

/** Route the mocked fetch by URL so the wizard can load status + mint a
 *  session for the handoff QR. */
function routeFetch() {
  const fn = vi.fn((input: string) => {
    const url = String(input);
    const body = url.startsWith("/api/setup/status")
      ? STATUS
      : url.startsWith("/api/setup/session")
        ? { token: "t", code: "123456", expires_at: "",
            url: "http://boombox.local:8090/setup/#t=t",
            base_url: "http://boombox.local:8090/setup/" }
        : { ok: true };
    return Promise.resolve({
      ok: true, status: 200, text: async () => JSON.stringify(body),
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const realLocation = window.location;

beforeEach(() => {
  vi.unstubAllGlobals();
  try { localStorage.clear(); } catch { /* fine */ }
  Object.defineProperty(window, "location", { value: realLocation, writable: true });
});

describe("Setup wizard", () => {
  it("loads status and shows the Welcome step with the device name", async () => {
    routeFetch();
    render(<App />);
    await waitFor(() =>
      expect(screen.getByText(/welcome to your boombox/i)).toBeTruthy());
    expect(screen.getByText("boombox.local")).toBeTruthy();
    expect(screen.getByText(/step 1 of 8/i)).toBeTruthy();
  });

  it("advances from Welcome to Name when Get started is clicked", async () => {
    routeFetch();
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /get started/i })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /get started/i }));
    await waitFor(() =>
      expect(screen.getByText(/name your boombox/i)).toBeTruthy());
    expect(screen.getByText(/step 2 of 8/i)).toBeTruthy();
    // The name field is prefilled from status.identity.name.
    expect((screen.getByLabelText(/device name/i) as HTMLInputElement).value)
      .toBe("Boombox");
  });
});

describe("Setup wizard — phone after completion", () => {
  it("renders the wizard after a typed code is redeemed against a redacted status", async () => {
    // A LAN phone (not the kiosk), no #t= hash.
    Object.defineProperty(window, "location", {
      value: { ...realLocation, hostname: "192.168.1.50", hash: "" },
      writable: true,
    });
    const REDACTED = {
      service_version: "1.0.0", complete: true,
      identity: STATUS.identity, skin: null,
    };
    const fn = vi.fn((input: string, init?: RequestInit) => {
      const url = String(input);
      const authed = !!(init?.headers as Record<string, string> | undefined)
        ?.["Authorization"];
      const body = url.startsWith("/api/setup/status")
        ? (authed ? { ...STATUS, complete: true } : REDACTED)
        : url.startsWith("/api/setup/session/redeem")
          ? { ok: true, token: "tok" }
          : { ok: true };
      return Promise.resolve({
        ok: true, status: 200, text: async () => JSON.stringify(body),
      });
    });
    vi.stubGlobal("fetch", fn);
    render(<App />);
    const input = await screen.findByLabelText(/setup code/i);
    fireEvent.change(input, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    // Used to blank the page (TypeError reading status.wifi.connected).
    await waitFor(() =>
      expect(screen.getByText(/step 1 of 8/i)).toBeTruthy());
    const statusCalls = fn.mock.calls.filter(([u]) =>
      String(u).startsWith("/api/setup/status"));
    expect(statusCalls.length).toBeGreaterThanOrEqual(2);
  });
});
