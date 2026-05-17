import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as api from "../libraryApi";

const realFetch = globalThis.fetch;

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  vi.restoreAllMocks();
  globalThis.fetch = realFetch;
});

function mockJson(body: unknown, ok = true, status = 200) {
  (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    ok, status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response);
}

describe("libraryApi", () => {
  it("getHealth parses last_sync_ts + syncing", async () => {
    mockJson({
      service_version: "0.1.0", navidrome_reachable: true,
      cache_present: true, cache_mount: "/media/X",
      last_sync_ts: 123, syncing: false,
    });
    const h = await api.getHealth();
    expect(h.last_sync_ts).toBe(123);
    expect(h.syncing).toBe(false);
  });

  it("pin sends source field when provided", async () => {
    mockJson({ ok: true });
    await api.pin("album", "al1", "favorite");
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/library/pin");
    expect(JSON.parse(call[1].body)).toMatchObject({
      kind: "album", id: "al1", mode: "pin", source: "favorite",
    });
  });

  it("unpin sends mode=unpin and source filter when provided", async () => {
    mockJson({ ok: true });
    await api.unpin("track", "t1", "favorite");
    const body = JSON.parse(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body
    );
    expect(body).toMatchObject({ kind: "track", id: "t1", mode: "unpin", source: "favorite" });
  });

  it("unpin without source omits the source field", async () => {
    mockJson({ ok: true });
    await api.unpin("track", "t1");
    const body = JSON.parse(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body
    );
    expect(body).toMatchObject({ kind: "track", id: "t1", mode: "unpin" });
    expect(body.source).toBeUndefined();
  });

  it("putSource throws on non-2xx with backend message", async () => {
    mockJson({ ok: false, error: "auth: wrong password" }, false, 400);
    await expect(
      api.putSource({ url: "u", username: "x", password: "y" })
    ).rejects.toThrow(/auth: wrong password/);
  });

  it("adoptCache posts mount_path", async () => {
    mockJson({ ok: true });
    await api.adoptCache("/media/DRIVE_B");
    const body = JSON.parse(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body
    );
    expect(body).toMatchObject({ mount_path: "/media/DRIVE_B" });
  });

  it("triggerStreamedCacheDownload uses query string id", async () => {
    mockJson({ ok: true });
    await api.triggerStreamedCacheDownload("t1");
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).toBe("/api/library/cache/streamed?id=t1");
  });

  it("browse returns the items array", async () => {
    mockJson({ items: [{ id: "ar1", name: "ABBA" }] });
    const items = await api.browse("artists");
    expect(items).toEqual([{ id: "ar1", name: "ABBA" }]);
  });

  it("search returns empty array for empty query without hitting the network", async () => {
    const r = await api.search("   ");
    expect(r).toEqual([]);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("getCacheCandidates returns the candidates array", async () => {
    mockJson({ candidates: [{ mount_path: "/m", label: "M", free_bytes: 0, total_bytes: 0 }] });
    const c = await api.getCacheCandidates();
    expect(c[0].mount_path).toBe("/m");
  });
});
