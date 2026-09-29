import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AccountsApp } from "./AccountsApp";

const BASE_R: Record<string, unknown> = {
  "GET /api/accounts/summary": {
    music: { state: "ok", detail: "" }, video: { state: "ok", detail: "" },
    streaming: { state: "ok", detail: "airplay" }, web: { state: "ok", detail: "" } },
  "GET /api/accounts/music": { url: "https://m", username: "bb", configured: true,
    reachable: true, last_sync_ts: 1790000000, syncing: false, prune_deferred: null },
  "GET /api/accounts/video": { mode: "remote", base: "https://v", key_set: true,
    kiosk_device_id: "boombox-markii-kiosk", kiosk_user: null },
  "GET /api/accounts/video/users": { users: [{ id: "u1", name: "jwc", admin: true }] },
  "GET /api/accounts/streaming": {
    airplay: { installed: true, active: true, name: "MarkII", password_set: false },
    spotify: { installed: false, active: false, name: "" } },
  "POST /api/accounts/video/kiosk-signin": { ok: true, user: "jwc" },
  "PUT /api/accounts/web-login": { ok: false, error: "current password is incorrect" },
};

let R: Record<string, unknown>;
/** Per-key queue of one-shot responses ({status, body}) consumed before R. */
let once: Record<string, { status: number; body: unknown }[]>;
let calls: { method: string; url: string; body?: unknown; headers?: Record<string, string> }[];

beforeEach(() => {
  calls = [];
  R = { ...BASE_R };
  once = {};
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined,
                 headers: init?.headers as Record<string, string> });
    const key = `${method} ${url}`;
    const queued = once[key]?.shift();
    const body = queued ? queued.body : (R[key] ?? { ok: true });
    const status = queued ? queued.status
      : (method === "GET" || (body as { ok?: boolean }).ok !== false) ? 200 : 400;
    const ok = status >= 200 && status < 300;
    return Promise.resolve({ ok, status,
      json: async () => body, text: async () => JSON.stringify(body) });
  }));
});

describe("AccountsApp", () => {
  it("renders the four cards with status", async () => {
    render(<AccountsApp />);
    expect(await screen.findByText("Music server")).toBeTruthy();
    expect(screen.getByText("Video server")).toBeTruthy();
    expect(screen.getByText("Streaming receivers")).toBeTruthy();
    expect(screen.getByText("Boombox web login")).toBeTruthy();
    expect((await screen.findAllByText("Connected")).length).toBeGreaterThan(0);
  });

  it("never renders stored secrets", async () => {
    render(<AccountsApp />);
    await screen.findByText("Music server");
    expect(document.body.innerHTML).not.toMatch(/apikey|s3cret/);
  });

  it("signs the kiosk in as the picked Jellyfin user", async () => {
    render(<AccountsApp />);
    fireEvent.click(await screen.findByRole("button", { name: /sign kiosk in as jwc/i }));
    await waitFor(() => expect(calls.some(c => c.url === "/api/accounts/video/kiosk-signin"
      && (c.body as { user_id: string }).user_id === "u1")).toBe(true));
    expect(await screen.findByText(/signed in as jwc/i)).toBeTruthy();
  });

  it("shows Spotify as not installed", async () => {
    render(<AccountsApp />);
    expect(await screen.findByText(/spotify connect.*not installed/i)).toBeTruthy();
  });

  it("sends JSON content type on writes and shows web-login errors", async () => {
    render(<AccountsApp />);
    await screen.findByText("Boombox web login");
    fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "correct horse battery" } });
    fireEvent.change(screen.getByLabelText(/repeat new password/i), { target: { value: "correct horse battery" } });
    fireEvent.click(screen.getByRole("button", { name: /change password/i }));
    expect(await screen.findByText(/current password is incorrect/)).toBeTruthy();
    const put = calls.find(c => c.method === "PUT")!;
    expect(put.headers?.["Content-Type"]).toBe("application/json");
    expect(put.body).toEqual({ current_password: "x", new_password: "correct horse battery" });
  });

  it("blocks mismatched or short new passwords client-side", async () => {
    render(<AccountsApp />);
    await screen.findByText("Boombox web login");
    const btn = () => screen.getByRole("button", { name: /change password/i }) as HTMLButtonElement;
    fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "short" } });
    expect(btn().disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "correct horse battery" } });
    fireEvent.change(screen.getByLabelText(/repeat new password/i), { target: { value: "correct horse batterY" } });
    expect(btn().disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/repeat new password/i), { target: { value: "correct horse battery" } });
    expect(btn().disabled).toBe(false);
  });

  it("reloads the music card and resets the form after a successful save", async () => {
    render(<AccountsApp />);
    const url = await screen.findByLabelText("Server URL") as HTMLInputElement;
    expect(url.value).toBe("https://m");
    fireEvent.change(url, { target: { value: "https://m2" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw2" } });
    R["GET /api/accounts/music"] = { ...(BASE_R["GET /api/accounts/music"] as object),
      url: "https://m2" };
    const musicSave = screen.getAllByRole("button", { name: /^save$/i })[0];
    fireEvent.click(musicSave);
    await waitFor(() => expect(calls.some(c => c.method === "PUT"
      && c.url === "/api/accounts/music")).toBe(true));
    const put = calls.find(c => c.method === "PUT" && c.url === "/api/accounts/music")!;
    expect(put.body).toEqual({ url: "https://m2", username: "bb", password: "pw2" });
    await waitFor(() => expect(calls.filter(c => c.method === "GET"
      && c.url === "/api/accounts/music").length).toBe(2));
    await waitFor(() =>
      expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe(""));
    expect((screen.getByLabelText("Server URL") as HTMLInputElement).value).toBe("https://m2");
  });

  it("offers Save anyway when the video server is unreachable and resends with force", async () => {
    once["PUT /api/accounts/video"] = [{ status: 400,
      body: { ok: false, error: "couldn't reach https://v", can_force: true } }];
    render(<AccountsApp />);
    await screen.findByLabelText("Base URL");
    const saves = screen.getAllByRole("button", { name: /^save$/i });
    fireEvent.click(saves[1]);
    expect(await screen.findByText(/couldn't reach https:\/\/v/)).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: /save anyway/i }));
    await waitFor(() => expect(calls.filter(c => c.method === "PUT"
      && c.url === "/api/accounts/video").length).toBe(2));
    const puts = calls.filter(c => c.method === "PUT" && c.url === "/api/accounts/video");
    expect(puts[0].body).toEqual({ mode: "remote", base: "https://v", api_key: "" });
    expect(puts[1].body).toEqual({ mode: "remote", base: "https://v", api_key: "", force: true });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /save anyway/i })).toBeNull());
  });

  it("does not offer Save anyway for plain validation errors", async () => {
    once["PUT /api/accounts/video"] = [{ status: 400, body: { ok: false, error: "bad base" } }];
    render(<AccountsApp />);
    await screen.findByLabelText("Base URL");
    fireEvent.click(screen.getAllByRole("button", { name: /^save$/i })[1]);
    expect(await screen.findByText(/bad base/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /save anyway/i })).toBeNull();
  });

  it("shows a problem message when the streaming helper fails", async () => {
    once["GET /api/accounts/streaming"] = [{ status: 502,
      body: { error: "receiver helper failed" } }];
    render(<AccountsApp />);
    expect(await screen.findByText(/receiver helper failed/)).toBeTruthy();
    expect(screen.getByText("Boombox web login")).toBeTruthy();
  });

  it("sends only changed AirPlay fields", async () => {
    R["GET /api/accounts/streaming"] = {
      airplay: { installed: true, active: true, name: "MarkII", password_set: true },
      spotify: { installed: true, active: true, name: "MarkII" } };
    render(<AccountsApp />);
    const name = await screen.findByLabelText("AirPlay name") as HTMLInputElement;
    expect((screen.getByLabelText("AirPlay password") as HTMLInputElement).placeholder)
      .toMatch(/saved — leave blank to keep/i);
    fireEvent.change(name, { target: { value: "Kitchen" } });
    fireEvent.click(screen.getByRole("button", { name: /save airplay/i }));
    await waitFor(() => expect(calls.some(c => c.method === "PUT"
      && c.url === "/api/accounts/streaming")).toBe(true));
    const put = calls.find(c => c.method === "PUT" && c.url === "/api/accounts/streaming")!;
    expect(put.body).toEqual({ airplay_name: "Kitchen" });
  });

  it("clears the AirPlay password when asked", async () => {
    R["GET /api/accounts/streaming"] = {
      airplay: { installed: true, active: true, name: "MarkII", password_set: true },
      spotify: { installed: false, active: false, name: "" } };
    render(<AccountsApp />);
    fireEvent.click(await screen.findByLabelText(/remove password/i));
    fireEvent.click(screen.getByRole("button", { name: /save airplay/i }));
    await waitFor(() => expect(calls.some(c => c.method === "PUT"
      && c.url === "/api/accounts/streaming")).toBe(true));
    const put = calls.find(c => c.method === "PUT" && c.url === "/api/accounts/streaming")!;
    expect(put.body).toEqual({ airplay_password_clear: true });
  });

  it("renames Spotify Connect and shows a server error", async () => {
    R["GET /api/accounts/streaming"] = {
      airplay: { installed: false, active: false, name: "" },
      spotify: { installed: true, active: true, name: "MarkII" } };
    R["PUT /api/accounts/streaming"] = { ok: false, error: "name contains a quote" };
    render(<AccountsApp />);
    expect(await screen.findByText(/airplay.*not installed/i)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Spotify name"), { target: { value: "Den\"" } });
    fireEvent.click(screen.getByRole("button", { name: /save spotify/i }));
    expect(await screen.findByText(/name contains a quote/)).toBeTruthy();
    const put = calls.find(c => c.method === "PUT" && c.url === "/api/accounts/streaming")!;
    expect(put.body).toEqual({ spotify_name: "Den\"" });
  });

  it("hides kiosk sign-in until an API key is stored", async () => {
    R["GET /api/accounts/video"] = { mode: "builtin", base: "", key_set: false,
      kiosk_device_id: "boombox-markii-kiosk", kiosk_user: null };
    render(<AccountsApp />);
    await screen.findByText("Video server");
    await waitFor(() => expect(calls.some(c => c.url === "/api/accounts/video")).toBe(true));
    expect(screen.queryByText(/kiosk sign-in/i)).toBeNull();
    expect(calls.some(c => c.url === "/api/accounts/video/users")).toBe(false);
  });

  it("hides kiosk sign-in for the built-in server", async () => {
    R["GET /api/accounts/video"] = { mode: "builtin", base: "http://127.0.0.1:8096",
      key_set: true, kiosk_device_id: "boombox-markii-kiosk", kiosk_user: null };
    render(<AccountsApp />);
    await screen.findByText("Video server");
    await waitFor(() => expect(calls.some(c => c.url === "/api/accounts/video")).toBe(true));
    expect(screen.queryByText(/kiosk sign-in/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /sign kiosk in/i })).toBeNull();
    expect(calls.some(c => c.url === "/api/accounts/video/users")).toBe(false);
  });

  it("signs the kiosk out", async () => {
    R["GET /api/accounts/video"] = { ...(BASE_R["GET /api/accounts/video"] as object),
      kiosk_user: "jwc" };
    render(<AccountsApp />);
    fireEvent.click(await screen.findByRole("button", { name: /sign out/i }));
    expect(await screen.findByRole("button", { name: /sign kiosk in as jwc/i })).toBeTruthy();
    expect(calls.some(c => c.method === "POST"
      && c.url === "/api/accounts/video/kiosk-signout")).toBe(true);
  });

  it("shows a kiosk sign-in failure", async () => {
    R["POST /api/accounts/video/kiosk-signin"] = { ok: false, error: "kiosk browser unreachable" };
    render(<AccountsApp />);
    fireEvent.click(await screen.findByRole("button", { name: /sign kiosk in as jwc/i }));
    expect(await screen.findByText(/kiosk browser unreachable/)).toBeTruthy();
  });

  it("shows a banner when the Boombox can't be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
    render(<AccountsApp />);
    expect((await screen.findAllByText(/couldn't reach the boombox/i)).length).toBeGreaterThan(0);
  });
});
