import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import { CacheAdoptOverlay } from "../CacheAdoptOverlay";
import * as api from "../../lib/libraryApi";

beforeEach(() => {
  vi.spyOn(api, "adoptCache").mockResolvedValue();
  vi.spyOn(api, "getHealth").mockResolvedValue({
    service_version: "0.1", navidrome_reachable: true, cache_present: false,
    cache_mount: null, last_sync_ts: 0, syncing: false,
  });
  vi.spyOn(api, "getCacheStats").mockResolvedValue({
    present: false, mount_path: null, capacity: 0, free: 0,
    pinned_bytes: 0, streamed_bytes: 0, reserved: 0,
  });
});
afterEach(() => vi.restoreAllMocks());

function fire(detail: { mount_path: string; label: string; free_bytes: number | null; total_bytes: number | null }) {
  window.dispatchEvent(new CustomEvent("boombox:cache-candidate", { detail }));
}

describe("CacheAdoptOverlay", () => {
  it("shows the prompt when a candidate is announced", async () => {
    const { findByText } = render(<CacheAdoptOverlay />);
    fire({ mount_path: "/media/DRIVE_B", label: "DRIVE_B", free_bytes: 230e9, total_bytes: 250e9 });
    await findByText(/DRIVE_B/);
  });

  it("Yes button calls adoptCache and closes", async () => {
    const { findByText, queryByText } = render(<CacheAdoptOverlay />);
    fire({ mount_path: "/media/X", label: "X", free_bytes: null, total_bytes: null });
    fireEvent.click(await findByText(/YES, USE/i));
    await waitFor(() => expect(api.adoptCache).toHaveBeenCalledWith("/media/X"));
    await waitFor(() => expect(queryByText(/Use this as the boombox/)).toBeNull());
  });

  it("No button closes without calling API", async () => {
    const { findByText, queryByText } = render(<CacheAdoptOverlay />);
    fire({ mount_path: "/media/Y", label: "Y", free_bytes: null, total_bytes: null });
    fireEvent.click(await findByText(/NO, BROWSE/i));
    expect(api.adoptCache).not.toHaveBeenCalled();
    await waitFor(() => expect(queryByText(/Use this as the boombox/)).toBeNull());
  });

  it("does not re-trigger after user dismissed the same drive", async () => {
    const { findByText, queryByText } = render(<CacheAdoptOverlay />);
    fire({ mount_path: "/media/Z", label: "Z", free_bytes: null, total_bytes: null });
    fireEvent.click(await findByText(/NO, BROWSE/i));
    fire({ mount_path: "/media/Z", label: "Z", free_bytes: null, total_bytes: null });
    expect(queryByText(/Use this as the boombox/)).toBeNull();
  });
});
