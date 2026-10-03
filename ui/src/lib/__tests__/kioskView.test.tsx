import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import {
  useReportKioskView, KIOSK_VIEW_URL, KIOSK_VIEW_HEARTBEAT_MS, type KioskView,
} from "../kioskView";

let fetchMock: ReturnType<typeof vi.fn>;

const posted = () =>
  fetchMock.mock.calls.map(([url, init]) => {
    expect(url).toBe(KIOSK_VIEW_URL);
    expect(init.method).toBe("POST");
    return JSON.parse(init.body).view;
  });

beforeEach(() => {
  vi.useFakeTimers();
  fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useReportKioskView", () => {
  it("reports the view on mount and on every change", () => {
    const { rerender } = renderHook(({ v }: { v: KioskView }) => useReportKioskView(v),
                                    { initialProps: { v: "home" } });
    expect(posted()).toEqual(["home"]);
    rerender({ v: "player" });
    expect(posted()).toEqual(["home", "player"]);
    rerender({ v: "home" });
    expect(posted()).toEqual(["home", "player", "home"]);
  });

  it("re-reports on a heartbeat so the server's home report stays fresh", () => {
    renderHook(() => useReportKioskView("home"));
    vi.advanceTimersByTime(KIOSK_VIEW_HEARTBEAT_MS * 2 + 1);
    expect(posted()).toEqual(["home", "home", "home"]);
  });

  it("stops the heartbeat on unmount", () => {
    const { unmount } = renderHook(() => useReportKioskView("home"));
    unmount();
    vi.advanceTimersByTime(KIOSK_VIEW_HEARTBEAT_MS * 3);
    expect(posted()).toEqual(["home"]);
  });

  it("beacons 'player' when the page goes away (kiosk off to Jellyfin)", () => {
    const beacon = vi.fn().mockReturnValue(true);
    vi.stubGlobal("navigator", { ...navigator, sendBeacon: beacon });
    renderHook(() => useReportKioskView("home"));
    window.dispatchEvent(new Event("pagehide"));
    expect(beacon).toHaveBeenCalledWith(KIOSK_VIEW_URL, JSON.stringify({ view: "player" }));
  });

  it("falls back to fetch when sendBeacon is unavailable", () => {
    vi.stubGlobal("navigator", { ...navigator, sendBeacon: undefined });
    renderHook(() => useReportKioskView("home"));
    window.dispatchEvent(new Event("pagehide"));
    expect(posted()).toEqual(["home", "player"]);
  });

  it("swallows a failed report", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    expect(() => renderHook(() => useReportKioskView("player"))).not.toThrow();
  });
});
