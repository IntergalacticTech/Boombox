import { describe, it, expect, beforeEach } from "vitest";
import { render, act } from "@testing-library/react";
import { SyncIndicator } from "../SyncIndicator";
import { _resetForTests, applyHealth } from "../homeLibrary";

function setHealth(opts: Partial<{
  reachable: boolean; syncing: boolean; lastSync: number; cachePresent: boolean;
}>) {
  applyHealth({
    service_version: "0.1",
    navidrome_reachable: opts.reachable ?? false,
    syncing: opts.syncing ?? false,
    last_sync_ts: opts.lastSync ?? 0,
    cache_present: opts.cachePresent ?? false,
    cache_mount: null,
  });
}

describe("SyncIndicator", () => {
  beforeEach(() => { _resetForTests(); });

  it("renders offline (grey) when source not configured", () => {
    const { getByLabelText } = render(<SyncIndicator />);
    expect(getByLabelText(/sync/i).getAttribute("data-state")).toBe("offline");
  });

  it("renders online_idle when reachable + recent sync", () => {
    const { getByLabelText } = render(<SyncIndicator />);
    act(() => setHealth({ reachable: true, lastSync: Date.now() / 1000 }));
    expect(getByLabelText(/sync/i).getAttribute("data-state")).toBe("online_idle");
  });

  it("renders syncing when syncing=true", () => {
    const { getByLabelText } = render(<SyncIndicator />);
    act(() => setHealth({ reachable: true, syncing: true }));
    expect(getByLabelText(/sync/i).getAttribute("data-state")).toBe("syncing");
  });

  it("renders online_due when reachable but no successful sync yet", () => {
    const { getByLabelText } = render(<SyncIndicator />);
    act(() => setHealth({ reachable: true, lastSync: 0 }));
    expect(getByLabelText(/sync/i).getAttribute("data-state")).toBe("online_due");
  });

  it("tapping dispatches boombox:open-settings-library", () => {
    const { getByLabelText } = render(<SyncIndicator />);
    let fired = false;
    const handler = () => { fired = true; };
    window.addEventListener("boombox:open-settings-library", handler);
    getByLabelText(/sync/i).dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(fired).toBe(true);
    window.removeEventListener("boombox:open-settings-library", handler);
  });
});
