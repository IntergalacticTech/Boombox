import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act, within } from "@testing-library/react";
import { StorageSection, PAUSED_TEXT, STORAGE_POLL_MS, STORAGE_IDLE_POLL_MS } from "./StorageSection";
import { adminSession } from "./session";
import type { PauseReason } from "./storage/types";

const GiB = 1024 ** 3;
const OVERVIEW = {
  drive: { present: true, internal: true, mount_path: "/opt/boombox/storage/music", total_bytes: 900 * GiB,
           free_bytes: 800 * GiB, reserve_bytes: 20 * GiB, music_bytes: 3 * GiB, kept_tracks: 412 },
  kept: [
    { kind: "album", id: "al1", name: "Blue", source: "user", tracks_total: 10, tracks_present: 4, bytes: 300 * 1024 ** 2 },
    { kind: "album", id: "al2", name: "Court and Spark", source: "starred", tracks_total: 11, tracks_present: 11, bytes: 400 * 1024 ** 2 },
  ],
  downloads: { active: true, queued: 12, in_flight: [{ id: "t5", title: "California" }, { id: "t6", title: "River" }],
               paused: null, failed: 2, no_space: 0 },
};

/** A route answer with its own HTTP status. */
class Reply {
  readonly status: number;
  readonly body: unknown;
  constructor(status: number, body: unknown) { this.status = status; this.body = body; }
}
/** A route answered by a function (e.g. a deferred promise). */
type Handler = () => Promise<Response>;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function mockFetch(routes: Record<string, unknown>, status = 200) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const v = key in routes ? routes[key] : { ok: false, error: `unmocked ${key}` };
    if (typeof v === "function") return (v as Handler)();
    if (v instanceof Reply) return json(v.body, v.status);
    return json(v, status);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => {
  adminSession.set("tok");
  (globalThis as { confirm?: () => boolean }).confirm = () => true;
});
afterEach(() => {
  vi.unstubAllGlobals();
  adminSession.clear("logout");
  delete (globalThis as { confirm?: () => boolean }).confirm;
});

describe("StorageSection", () => {
  it("is locked until the web password is entered", async () => {
    adminSession.clear("logout");
    render(<StorageSection desktop={false} />);
    expect(await screen.findByLabelText("Web password")).toBeTruthy();
  });

  it("shows the drive, the downloads and the kept items", async () => {
    mockFetch({ "GET /api/accounts/storage": OVERVIEW });
    render(<StorageSection desktop={false} />);
    expect(await screen.findByText("Internal drive")).toBeTruthy();
    expect(screen.getByText("2 downloading · 12 queued")).toBeTruthy();
    expect(screen.getByText(/California/)).toBeTruthy();
    expect(screen.getByText("2 failed")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove Blue" })).toBeTruthy();
    const starred = screen.getByText("Court and Spark").closest("li")!;
    expect(starred.textContent).toContain("Unstar in Navidrome to remove");
    expect(starred.querySelector("button")).toBeNull();
  });

  it.each(["streaming", "hot", "offline", "low_space"] as PauseReason[])("explains a pause: %s", async (reason) => {
    mockFetch({ "GET /api/accounts/storage": { ...OVERVIEW, downloads: { ...OVERVIEW.downloads, paused: reason } } });
    render(<StorageSection desktop={false} />);
    expect(await screen.findByText(PAUSED_TEXT[reason])).toBeTruthy();
  });

  it("says when the drive is below the reserve and how many were skipped", async () => {
    mockFetch({ "GET /api/accounts/storage": {
      ...OVERVIEW, drive: { ...OVERVIEW.drive, free_bytes: 10 * GiB },
      downloads: { ...OVERVIEW.downloads, no_space: 3 } } });
    render(<StorageSection desktop={false} />);
    expect(await screen.findByText(/Low space — downloads stop until more than 20.0 GB is free/)).toBeTruthy();
    expect(screen.getByText("3 skipped — not enough space")).toBeTruthy();
  });

  it("Remove posts the item and reports what was freed", async () => {
    const fetchMock = mockFetch({
      "GET /api/accounts/storage": OVERVIEW,
      "POST /api/accounts/storage/remove": { ok: true, removed_tracks: 4, freed_bytes: 300 * 1024 ** 2 },
    });
    render(<StorageSection desktop={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove Blue" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/accounts/storage/remove",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ kind: "album", id: "al1" }) })));
    expect(await screen.findByText("Removed Blue — 300 MB freed.")).toBeTruthy();
  });

  it("Retry failed re-queues them", async () => {
    mockFetch({ "GET /api/accounts/storage": OVERVIEW,
                "POST /api/accounts/storage/retry": { ok: true, retried: 2 } });
    render(<StorageSection desktop={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry failed" }));
    expect(await screen.findByText("Retrying 2 downloads.")).toBeTruthy();
  });

  it("library down: a message and Retry", async () => {
    mockFetch({ "GET /api/accounts/storage": { ok: false, error: "library service not answering" } }, 502);
    render(<StorageSection desktop={false} />);
    const msg = (await screen.findByText("library service not answering")).closest("[role=status]")!;
    expect(within(msg as HTMLElement).getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("an expired admin session goes back to the lock screen", async () => {
    mockFetch({ "GET /api/accounts/storage": { error: "admin session required" } }, 401);
    render(<StorageSection desktop={false} />);
    expect(await screen.findByLabelText("Web password")).toBeTruthy();
  });
  it("polls while open and stops when unmounted or locked", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      const fetchMock = mockFetch({ "GET /api/accounts/storage": OVERVIEW });
      // Count overview polls only (the Uploads panel browses once per mount).
      const polls = () => fetchMock.mock.calls.filter(([u]) => u === "/api/accounts/storage").length;
      const { unmount } = render(<StorageSection desktop={false} />);
      await screen.findByText("Internal drive");
      expect(polls()).toBe(1);
      await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS);
      expect(polls()).toBe(2);
      unmount();
      await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS * 3);
      expect(polls()).toBe(2);

      render(<StorageSection desktop={false} />);
      await waitFor(() => expect(polls()).toBe(3));
      act(() => adminSession.clear("logout"));
      expect(await screen.findByLabelText("Web password")).toBeTruthy();
      await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS * 3);
      expect(polls()).toBe(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("the Uploads panel browses the music folder with the admin session", async () => {
    const fetchMock = mockFetch({
      "GET /api/accounts/storage": OVERVIEW,
      "GET /api/accounts/storage/files/browse?path=": {
        path: "", parent: null, entries: [{ name: "uploads", kind: "dir", tracks: 3 }] },
    });
    render(<StorageSection desktop />);
    expect(await screen.findByText("uploads")).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Upload" })).toBeTruthy();
    const call = fetchMock.mock.calls.find(([u]) => u === "/api/accounts/storage/files/browse?path=")!;
    expect((call[1] as RequestInit).headers).toEqual(expect.objectContaining({ Authorization: "Bearer tok" }));
  });
  it("card-bound items say to unbind the card and have no Remove", async () => {
    mockFetch({ "GET /api/accounts/storage": { ...OVERVIEW, kept: [
      { kind: "album", id: "al9", name: "Hejira", source: "card", tracks_total: 9, tracks_present: 9, bytes: 1024 },
      { kind: "card_tracks", id: "", name: "Songs on cards", source: "card", tracks_total: 2, tracks_present: 1, bytes: 1024 },
    ] } });
    render(<StorageSection desktop={false} />);
    for (const name of ["Hejira", "Songs on cards"]) {
      const row = (await screen.findByText(name)).closest("li")!;
      expect(row.textContent).toContain("On an RFID card — unbind the card to remove");
      expect(row.textContent).toContain(" · card · ");
      expect(row.querySelector("button")).toBeNull();
    }
    expect(screen.getByText("Songs on cards").closest("li")!.textContent).toContain("Songs · card");
  });

  it("polls every 15 s when idle and every 5 s while downloading", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      const IDLE = { ...OVERVIEW, downloads: { ...OVERVIEW.downloads, in_flight: [], queued: 0 } };
      const QUEUED_ONLY = { ...IDLE, downloads: { ...IDLE.downloads, queued: 3 } };
      const answers = [OVERVIEW, IDLE, QUEUED_ONLY, QUEUED_ONLY];
      let n = 0;
      const fetchMock = mockFetch({ "GET /api/accounts/storage": async () => json(answers[Math.min(n++, 3)]) });
      const polls = () => fetchMock.mock.calls.filter(([u]) => u === "/api/accounts/storage").length;
      render(<StorageSection desktop={false} />);
      await screen.findByText("Internal drive");
      expect(polls()).toBe(1);
      await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS);   // downloading → 5 s
      expect(polls()).toBe(2);
      await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS);   // idle → not yet
      expect(polls()).toBe(2);
      await vi.advanceTimersByTimeAsync(STORAGE_IDLE_POLL_MS - STORAGE_POLL_MS);
      expect(polls()).toBe(3);
      await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS);   // queued > 0 → 5 s again
      expect(polls()).toBe(4);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a slow poll neither blocks the next one nor overwrites a newer answer", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      let releaseSlow!: (r: Response) => void;
      const NEWER = { ...OVERVIEW, downloads: { ...OVERVIEW.downloads, failed: 0 } };
      let n = 0;
      const fetchMock = mockFetch({ "GET /api/accounts/storage": () => {
        n += 1;
        if (n === 1) return Promise.resolve(json(OVERVIEW));
        if (n === 2) return new Promise<Response>((res) => { releaseSlow = res; });
        return Promise.resolve(json(NEWER));
      } });
      const polls = () => fetchMock.mock.calls.filter(([u]) => u === "/api/accounts/storage").length;
      render(<StorageSection desktop={false} />);
      expect(await screen.findByText("2 failed")).toBeTruthy();
      await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS);   // #2 hangs
      expect(polls()).toBe(2);
      await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS);   // not stuck behind it
      expect(polls()).toBe(3);
      expect(await screen.findByText("0 failed")).toBeTruthy();
      await act(async () => { releaseSlow(json(OVERVIEW)); });
      expect(screen.getByText("0 failed")).toBeTruthy();
      expect(screen.queryByText("2 failed")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("a refused Remove shows as an error", async () => {
    mockFetch({
      "GET /api/accounts/storage": OVERVIEW,
      "POST /api/accounts/storage/remove": new Reply(409, { ok: false, error: "unstar in Navidrome to remove" }),
    });
    render(<StorageSection desktop={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove Blue" }));
    const msg = await screen.findByText("unstar in Navidrome to remove");
    expect(msg.getAttribute("role")).toBe("alert");
  });

  it("a refused Retry shows as an error", async () => {
    mockFetch({
      "GET /api/accounts/storage": OVERVIEW,
      "POST /api/accounts/storage/retry": new Reply(409, { ok: false, error: "downloads aren't running" }),
    });
    render(<StorageSection desktop={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry failed" }));
    const msg = await screen.findByText("downloads aren't running");
    expect(msg.getAttribute("role")).toBe("alert");
  });

  it.each([
    ["the library is down", new Reply(502, { ok: false, error: "library service not answering" })],
    ["the overview is loading", () => new Promise<Response>(() => {})],
  ])("Uploads still work while %s", async (_why, answer) => {
    mockFetch({
      "GET /api/accounts/storage": answer,
      "GET /api/accounts/storage/files/browse?path=": {
        path: "", parent: null, entries: [{ name: "uploads", kind: "dir", tracks: 3 }] },
    });
    render(<StorageSection desktop={false} />);
    expect(await screen.findByText("uploads")).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Upload" })).toBeTruthy();
  });

  async function uploadOne() {
    await screen.findByText("uploads");
    const input = screen.getByLabelText("Choose files to upload") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "a.mp3", { type: "audio/mpeg" })] } });
  }
  const BROWSE = { "GET /api/accounts/storage": OVERVIEW,
    "GET /api/accounts/storage/files/browse?path=": {
      path: "", parent: null, entries: [{ name: "uploads", kind: "dir", tracks: 3 }] } };

  it("an upload answered 401 drops the admin session", async () => {
    mockFetch({ ...BROWSE,
      "POST /api/accounts/storage/files/upload": new Reply(401, { error: "admin session required" }) });
    render(<StorageSection desktop={false} />);
    await uploadOne();
    expect(await screen.findByLabelText("Web password")).toBeTruthy();
    expect(adminSession.token()).toBeNull();
  });

  it("an upload answered 507 shows the server's message", async () => {
    mockFetch({ ...BROWSE,
      "POST /api/accounts/storage/files/upload": new Reply(507, { error: "not enough space on the drive" }) });
    render(<StorageSection desktop={false} />);
    await uploadOne();
    expect(await screen.findByText("not enough space on the drive")).toBeTruthy();
  });
});
