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

beforeEach(() => {
  vi.unstubAllGlobals();
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
