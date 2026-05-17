import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor, act } from "@testing-library/react";
import { CachePanel } from "../CachePanel";
import { _resetForTests, applyCacheStats } from "../homeLibrary";
import * as api from "../libraryApi";

beforeEach(() => {
  _resetForTests();
  vi.spyOn(api, "clearStreamedCache").mockResolvedValue({ cleared: 0 });
  vi.spyOn(api, "getHealth").mockResolvedValue({
    service_version: "0.1", navidrome_reachable: true, cache_present: true,
    cache_mount: "/m", last_sync_ts: 0, syncing: false,
  });
  vi.spyOn(api, "getCacheStats").mockResolvedValue({
    present: false, mount_path: null, capacity: 0, free: 0,
    pinned_bytes: 0, streamed_bytes: 0, reserved: 0,
  });
  vi.stubGlobal("confirm", () => true);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("CachePanel", () => {
  it("renders 'cache drive offline' when stats.present=false", () => {
    const { getByText } = render(<CachePanel />);
    act(() => applyCacheStats({
      present: false, mount_path: null,
      capacity: 0, free: 0, pinned_bytes: 0, streamed_bytes: 0, reserved: 0,
    }));
    getByText(/Cache drive offline/i);
  });

  it("stacked bar widths sum to 100% (within rounding)", () => {
    const { container } = render(<CachePanel />);
    act(() => applyCacheStats({
      present: true, mount_path: "/m",
      capacity: 100, free: 50, pinned_bytes: 30, streamed_bytes: 15, reserved: 5,
    }));
    const segs = Array.from(container.querySelectorAll('[data-cache-seg]')) as HTMLElement[];
    expect(segs.length).toBe(4);
    const total = segs.reduce((s, el) => s + parseFloat(el.style.width), 0);
    expect(Math.round(total)).toBe(100);
  });

  it("Clear streamed cache button calls API", async () => {
    const { getByText } = render(<CachePanel />);
    act(() => applyCacheStats({
      present: true, mount_path: "/m",
      capacity: 100, free: 50, pinned_bytes: 30, streamed_bytes: 15, reserved: 5,
    }));
    fireEvent.click(getByText(/Clear streamed/i));
    await waitFor(() => expect(api.clearStreamedCache).toHaveBeenCalled());
  });

  it("renders mount path when present", () => {
    const { getByText } = render(<CachePanel />);
    act(() => applyCacheStats({
      present: true, mount_path: "/media/BOOMBOX_CACHE",
      capacity: 100, free: 50, pinned_bytes: 30, streamed_bytes: 15, reserved: 5,
    }));
    getByText("/media/BOOMBOX_CACHE");
  });
});
