import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AccountsSection, ACCOUNTS_DESKTOP_COLUMNS } from "../AccountsSection";
import { adminSession } from "../session";

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
  adminSession.set("tok");
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
    render(<AccountsSection desktop />);
    expect(await screen.findByText("Music server")).toBeTruthy();
    expect(screen.getByText("Video server")).toBeTruthy();
    expect(screen.getByText("Streaming receivers")).toBeTruthy();
    expect(screen.getByText("Boombox web login")).toBeTruthy();
    expect((await screen.findAllByText("Connected")).length).toBeGreaterThan(0);
  });

  it("never renders stored secrets", async () => {
    render(<AccountsSection desktop />);
    await screen.findByText("Music server");
    expect(document.body.innerHTML).not.toMatch(/apikey|s3cret/);
  });

  it("signs the kiosk in as the picked Jellyfin user", async () => {
    render(<AccountsSection desktop />);
    fireEvent.click(await screen.findByRole("button", { name: /sign kiosk in as jwc/i }));
    await waitFor(() => expect(calls.some(c => c.url === "/api/accounts/video/kiosk-signin"
      && (c.body as { user_id: string }).user_id === "u1")).toBe(true));
    expect(await screen.findByText(/signed in as jwc/i)).toBeTruthy();
  });

  it("shows Spotify as not installed", async () => {
    render(<AccountsSection desktop />);
    expect(await screen.findByText(/spotify connect.*not installed/i)).toBeTruthy();
  });

  it("sends JSON content type on writes and shows web-login errors", async () => {
    render(<AccountsSection desktop />);
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
    render(<AccountsSection desktop />);
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
    render(<AccountsSection desktop />);
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
    render(<AccountsSection desktop />);
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
    render(<AccountsSection desktop />);
    await screen.findByLabelText("Base URL");
    fireEvent.click(screen.getAllByRole("button", { name: /^save$/i })[1]);
    expect(await screen.findByText(/bad base/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /save anyway/i })).toBeNull();
  });

  it("shows a problem message when the streaming helper fails", async () => {
    once["GET /api/accounts/streaming"] = [{ status: 502,
      body: { error: "receiver helper failed" } }];
    render(<AccountsSection desktop />);
    expect(await screen.findByText(/receiver helper failed/)).toBeTruthy();
    expect(screen.getByText("Boombox web login")).toBeTruthy();
  });

  it("sends only changed AirPlay fields", async () => {
    R["GET /api/accounts/streaming"] = {
      airplay: { installed: true, active: true, name: "MarkII", password_set: true },
      spotify: { installed: true, active: true, name: "MarkII" } };
    render(<AccountsSection desktop />);
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
    render(<AccountsSection desktop />);
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
    render(<AccountsSection desktop />);
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
    render(<AccountsSection desktop />);
    await screen.findByText("Video server");
    await waitFor(() => expect(calls.some(c => c.url === "/api/accounts/video")).toBe(true));
    expect(screen.queryByText(/kiosk sign-in/i)).toBeNull();
    expect(calls.some(c => c.url === "/api/accounts/video/users")).toBe(false);
  });

  it("hides kiosk sign-in for the built-in server", async () => {
    R["GET /api/accounts/video"] = { mode: "builtin", base: "http://127.0.0.1:8096",
      key_set: true, kiosk_device_id: "boombox-markii-kiosk", kiosk_user: null };
    render(<AccountsSection desktop />);
    await screen.findByText("Video server");
    await waitFor(() => expect(calls.some(c => c.url === "/api/accounts/video")).toBe(true));
    expect(screen.queryByText(/kiosk sign-in/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /sign kiosk in/i })).toBeNull();
    expect(calls.some(c => c.url === "/api/accounts/video/users")).toBe(false);
  });

  it("signs the kiosk out", async () => {
    R["GET /api/accounts/video"] = { ...(BASE_R["GET /api/accounts/video"] as object),
      kiosk_user: "jwc" };
    render(<AccountsSection desktop />);
    fireEvent.click(await screen.findByRole("button", { name: /sign out/i }));
    expect(await screen.findByRole("button", { name: /sign kiosk in as jwc/i })).toBeTruthy();
    expect(calls.some(c => c.method === "POST"
      && c.url === "/api/accounts/video/kiosk-signout")).toBe(true);
  });

  it("shows a kiosk sign-in failure", async () => {
    R["POST /api/accounts/video/kiosk-signin"] = { ok: false, error: "kiosk browser unreachable" };
    render(<AccountsSection desktop />);
    fireEvent.click(await screen.findByRole("button", { name: /sign kiosk in as jwc/i }));
    expect(await screen.findByText(/kiosk browser unreachable/)).toBeTruthy();
  });

  it("shows a banner when the Boombox can't be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
    render(<AccountsSection desktop />);
    expect((await screen.findAllByText(/couldn't reach the boombox/i)).length).toBeGreaterThan(0);
  });
});

describe("Admin gate", () => {
  it("sends the admin bearer token on every call", async () => {
    render(<AccountsSection desktop />);
    await screen.findByText("Music server");
    await waitFor(() => expect(calls.length).toBeGreaterThan(3));
    expect(calls.every((c) => c.headers?.Authorization === "Bearer tok")).toBe(true);
  });

  it("locked: shows the lock screen, unlocks with the web password", async () => {
    adminSession.clear("logout");
    once["POST /api/accounts/session"] = [{ status: 200,
      body: { ok: true, token: "fresh", expires_at: 1 } }];
    render(<AccountsSection desktop />);
    expect(screen.queryByText("Music server")).toBeNull();
    fireEvent.change(screen.getByLabelText("Web password"),
      { target: { value: "correct horse battery" } });
    fireEvent.click(screen.getByRole("button", { name: /unlock/i }));
    expect(await screen.findByText("Music server")).toBeTruthy();
    expect(calls.find((c) => c.url === "/api/accounts/session")!.body)
      .toEqual({ password: "correct horse battery" });
    expect(adminSession.token()).toBe("fresh");
  });

  it("explains a lockout", async () => {
    adminSession.clear("logout");
    once["POST /api/accounts/session"] = [{ status: 429,
      body: { ok: false, error: "too many wrong passwords — try again later", retry_after: 240 } }];
    render(<AccountsSection desktop />);
    fireEvent.change(screen.getByLabelText("Web password"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /unlock/i }));
    expect(await screen.findByText(/try again in 4 minutes/i)).toBeTruthy();
  });

  it("an expired session drops back to the lock screen", async () => {
    once["GET /api/accounts/summary"] = [{ status: 401, body: { error: "admin session required" } }];
    render(<AccountsSection desktop />);
    expect(await screen.findByText(/session expired/i)).toBeTruthy();
    expect(adminSession.token()).toBeNull();
  });

  it("Lock logs out", async () => {
    render(<AccountsSection desktop />);
    await screen.findByText("Music server");
    fireEvent.click(screen.getByRole("button", { name: /lock admin/i }));
    expect(await screen.findByLabelText("Web password")).toBeTruthy();
    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/accounts/session"
      && c.headers?.Authorization === "Bearer tok")).toBe(true);
  });

  it("changing the web password keeps you unlocked", async () => {
    R["PUT /api/accounts/web-login"] = { ok: true, updated: ["web", "samba"] };
    render(<AccountsSection desktop />);
    await screen.findByText("Boombox web login");
    fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "old password 1" } });
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "correct horse battery" } });
    fireEvent.change(screen.getByLabelText(/repeat new password/i), { target: { value: "correct horse battery" } });
    fireEvent.click(screen.getByRole("button", { name: /change password/i }));
    expect(await screen.findByText(/password changed/i)).toBeTruthy();
    expect(adminSession.token()).toBe("tok");
  });

  it("desktop fits as many >= 320 px cards as the column allows; phones get one", async () => {
    const { unmount } = render(<AccountsSection desktop />);
    const grid = await screen.findByTestId("accounts-grid");
    expect(grid.dataset.columns).toBe("auto");
    expect(ACCOUNTS_DESKTOP_COLUMNS).toBe("repeat(auto-fit, minmax(min(320px, 100%), 1fr))");
    expect(grid.style.gridTemplateColumns).toContain("auto-fit");
    expect(grid.style.gridTemplateColumns).not.toContain("repeat(2");
    unmount();
    render(<AccountsSection desktop={false} />);
    const phone = await screen.findByTestId("accounts-grid");
    expect(phone.dataset.columns).toBe("1");
    expect(phone.style.gridTemplateColumns).toBe("minmax(0, 1fr)");
  });
});
