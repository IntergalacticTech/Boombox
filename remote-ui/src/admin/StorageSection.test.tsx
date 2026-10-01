import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { StorageSection, PAUSED_TEXT, STORAGE_POLL_MS } from "./StorageSection";
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

function mockFetch(routes: Record<string, unknown>, status = 200) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const body = key in routes ? routes[key] : { ok: false, error: `unmocked ${key}` };
    return new Response(JSON.stringify(body), { status });
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
    expect(await screen.findByText("library service not answering")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
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
      const { unmount } = render(<StorageSection desktop={false} />);
      await screen.findByText("Internal drive");
      expect(fetchMock).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      unmount();
      await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS * 3);
      expect(fetchMock).toHaveBeenCalledTimes(2);

      render(<StorageSection desktop={false} />);
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
      act(() => adminSession.clear("logout"));
      expect(await screen.findByLabelText("Web password")).toBeTruthy();
      await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS * 3);
      expect(fetchMock).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });
});
