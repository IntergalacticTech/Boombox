import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  _resetForTests, useSyncStatus, useCacheStats, applyHealth, applyCacheStats,
  useHomeLibraryOffline,
} from "../homeLibrary";

beforeEach(() => { _resetForTests(); });

describe("homeLibrary store", () => {
  it("useSyncStatus reflects latest health snapshot", () => {
    const { result } = renderHook(() => useSyncStatus());
    expect(result.current.reachable).toBe(false);
    act(() => {
      applyHealth({
        service_version: "0.1", navidrome_reachable: true, cache_present: true,
        cache_mount: "/m", last_sync_ts: 100, syncing: false,
      });
    });
    expect(result.current.reachable).toBe(true);
    expect(result.current.lastSyncTs).toBe(100);
    expect(result.current.cachePresent).toBe(true);
  });

  it("useCacheStats publishes on update", () => {
    const { result } = renderHook(() => useCacheStats());
    expect(result.current).toBeNull();
    act(() => {
      applyCacheStats({
        present: true, mount_path: "/m", capacity: 100, free: 50,
        pinned_bytes: 10, streamed_bytes: 20, reserved: 5,
      });
    });
    expect(result.current?.free).toBe(50);
  });

  it("syncing flag flips back to false", () => {
    const { result } = renderHook(() => useSyncStatus());
    act(() => applyHealth({
      service_version: "0.1", navidrome_reachable: true, cache_present: false,
      cache_mount: null, last_sync_ts: 100, syncing: true,
    }));
    expect(result.current.syncing).toBe(true);
    act(() => applyHealth({
      service_version: "0.1", navidrome_reachable: true, cache_present: false,
      cache_mount: null, last_sync_ts: 100, syncing: false,
    }));
    expect(result.current.syncing).toBe(false);
  });
});

describe("useHomeLibraryOffline", () => {
  const health = {
    service_version: "0.1", cache_present: true, cache_mount: "/m",
    last_sync_ts: 1, syncing: false,
  };

  it("is false before any health answer (unknown reads as online)", () => {
    const { result } = renderHook(() => useHomeLibraryOffline());
    expect(result.current).toBe(false);
  });

  it("is true only when Navidrome is known to be unreachable", () => {
    const { result } = renderHook(() => useHomeLibraryOffline());
    act(() => applyHealth({ ...health, navidrome_reachable: false, reachability_known: false }));
    expect(result.current).toBe(false);
    act(() => applyHealth({ ...health, navidrome_reachable: false, reachability_known: true }));
    expect(result.current).toBe(true);
    act(() => applyHealth({ ...health, navidrome_reachable: true, reachability_known: true }));
    expect(result.current).toBe(false);
  });

  it("trusts navidrome_reachable from servers without reachability_known", () => {
    const { result } = renderHook(() => useHomeLibraryOffline());
    act(() => applyHealth({ ...health, navidrome_reachable: false }));
    expect(result.current).toBe(true);
  });
});
