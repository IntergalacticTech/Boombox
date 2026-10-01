import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within, act } from "@testing-library/react";
import { HomeLibrary } from "./HomeLibrary";
import { Music } from "./Music";
import { ApiProvider, ApiError, type RemoteApi } from "../lib/api";
import { clearHomeCache } from "../lib/homeLibrary";

const ALBUMS = { items: [
  { id: "al1", name: "Blue", artist_id: "ar1", year: 1971, art_id: "al-1" },
  { id: "al2", name: "Court and Spark", artist_id: "ar1", year: 1974 },
] };
const ARTISTS = { items: [{ id: "ar1", name: "Joni Mitchell", album_count: 2 }] };
const ALBUM = { album: { id: "al1", name: "Blue", artist: "Joni Mitchell", year: 1971, art_id: "al-1" },
  tracks: [
    { id: "t1", title: "All I Want", duration: 214 },
    { id: "t2", title: "My Old Man", duration: 213 },
    { id: "t3", title: "Little Green", duration: 206 },
  ] };
const ARTIST = { artist: { id: "ar1", name: "Joni Mitchell" },
  albums: [{ id: "al1", name: "Blue" }, { id: "al2", name: "Court and Spark" }] };
const ALBUM2 = { album: { id: "al2", name: "Court and Spark" }, tracks: [{ id: "t9", title: "Help Me" }] };

function mockApi(overrides: Partial<RemoteApi> = {}): RemoteApi {
  return {
    base: "http://pi/",
    get: vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/home/browse?type=albums") return ALBUMS;
      if (p === "api/remote/home/browse?type=artists") return ARTISTS;
      if (p === "api/remote/home/album/al1") return ALBUM;
      if (p === "api/remote/home/album/al2") return ALBUM2;
      if (p === "api/remote/home/artist/ar1") return ARTIST;
      if (p.startsWith("api/remote/home/search")) {
        return { results: [{ content_type: "track", id: "t2", title: "My Old Man" }] };
      }
      throw new Error(`unmocked ${p}`);
    }),
    post: vi.fn().mockResolvedValue({ ok: true, count: 3, skipped: 0 }),
    uploadFiles: vi.fn(),
    ...overrides,
  };
}

function wrap(api: RemoteApi, params: string[], navigate = vi.fn()) {
  return render(<ApiProvider api={api}><HomeLibrary params={params} navigate={navigate} /></ApiProvider>);
}

beforeEach(() => clearHomeCache());

describe("HomeLibrary", () => {
  it("lists albums as tiles and opens one", async () => {
    const navigate = vi.fn();
    wrap(mockApi(), [], navigate);
    fireEvent.click(await screen.findByRole("button", { name: /Blue/ }));
    expect(navigate).toHaveBeenCalledWith("music", ["home", "album", "al1"]);
  });

  it("switches lists through the hash", async () => {
    const navigate = vi.fn();
    wrap(mockApi(), ["artists"], navigate);
    expect(await screen.findByText("Joni Mitchell")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Playlists" }));
    expect(navigate).toHaveBeenCalledWith("music", ["home", "playlists"]);
  });

  it("filters the loaded list as you type", async () => {
    wrap(mockApi(), []);
    await screen.findByText("Court and Spark");
    fireEvent.change(screen.getByLabelText("Search the Home Library"), { target: { value: "cou" } });
    expect(screen.queryByRole("button", { name: /^Blue/ })).toBeNull();
    expect(screen.getByText("Court and Spark")).toBeTruthy();
  });

  it("album: Play all, play from a track, queue one track", async () => {
    const api = mockApi();
    wrap(api, ["album", "al1"]);
    fireEvent.click(await screen.findByRole("button", { name: "Play all" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t1", "t2", "t3"], mode: "play" }));
    expect(await screen.findByText("Playing Blue — 3 tracks.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Play from My Old Man" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t2", "t3"], mode: "play" }));
    fireEvent.click(screen.getByRole("button", { name: "Queue My Old Man" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t2"], mode: "queue" }));
  });

  it("artist: Play all expands every album's tracks", async () => {
    const api = mockApi();
    wrap(api, ["artist", "ar1"]);
    fireEvent.click(await screen.findByRole("button", { name: "Play all" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t1", "t2", "t3", "t9"], mode: "play" }));
  });

  it("reports skipped offline tracks and the server's all-offline message", async () => {
    const post = vi.fn()
      .mockResolvedValueOnce({ ok: true, count: 2, skipped: 1 })
      .mockRejectedValueOnce(new ApiError(409,
        '{"ok":false,"error":"none of these tracks can play right now — they aren\'t cached and the Home Library server is unreachable"}'));
    wrap(mockApi({ post }), ["album", "al1"]);
    fireEvent.click(await screen.findByRole("button", { name: "Play all" }));
    expect(await screen.findByText("Playing Blue — 2 tracks (1 not available offline).")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Queue all" }));
    expect(await screen.findByText(/none of these tracks can play right now/)).toBeTruthy();
  });

  it("library down shows a message with Retry", async () => {
    const get = vi.fn()
      .mockRejectedValueOnce(new ApiError(502, '{"ok":false,"error":"library service not answering"}'))
      .mockResolvedValue(ALBUMS);
    wrap(mockApi({ get }), []);
    expect(await screen.findByText("library service not answering")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Court and Spark")).toBeTruthy();
  });

  it("server search results play a track", async () => {
    const api = mockApi();
    wrap(api, []);
    await screen.findByText("Blue");
    fireEvent.change(screen.getByLabelText("Search the Home Library"), { target: { value: "old man" } });
    fireEvent.click(await screen.findByRole("button", { name: "Play My Old Man" }, { timeout: 2000 }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t2"], mode: "play" }));
  });
});

describe("HomeLibrary play cap", () => {
  const BIG = { playlist: { id: "pl1", name: "Everything" },
    tracks: Array.from({ length: 1200 }, (_, i) => ({ id: `t${i}`, title: `Song ${i}` })) };

  it("caps Play all and Play from at 500 tracks and says so", async () => {
    const get = vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/home/playlist/pl1") return BIG;
      throw new Error(`unmocked ${p}`);
    });
    const post = vi.fn().mockResolvedValue({ ok: true, count: 500, skipped: 0 });
    wrap(mockApi({ get, post }), ["playlist", "pl1"]);
    fireEvent.click(await screen.findByRole("button", { name: "Play all" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const body = post.mock.calls[0][1] as { ids: string[]; mode: string };
    expect(body.mode).toBe("play");
    expect(body.ids).toHaveLength(500);
    expect(body.ids[0]).toBe("t0");
    expect(body.ids[499]).toBe("t499");
    expect(await screen.findByText(/first 500 tracks/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Play from Song 900" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    const from = post.mock.calls[1][1] as { ids: string[] };
    expect(from.ids).toHaveLength(300);
    expect(from.ids[0]).toBe("t900");

    fireEvent.click(screen.getByRole("button", { name: "Play from Song 100" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(3));
    const from2 = post.mock.calls[2][1] as { ids: string[] };
    expect(from2.ids).toHaveLength(500);
    expect(from2.ids[0]).toBe("t100");
    expect(from2.ids[499]).toBe("t599");

    fireEvent.click(screen.getByRole("button", { name: "Queue all" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(4));
    expect((post.mock.calls[3][1] as { ids: string[] }).ids).toHaveLength(500);
  }, 20_000); // renders 1200 rows — slower CI runners need more than the 5 s default

  it("caps an artist's Play all at 500 and says so", async () => {
    const album = (n: string) => ({ album: { id: n, name: n },
      tracks: Array.from({ length: 300 }, (_, i) => ({ id: `${n}-${i}`, title: `${n} ${i}` })) });
    const get = vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/home/artist/big") {
        return { artist: { id: "big", name: "Prolific" },
                 albums: [{ id: "x", name: "x" }, { id: "y", name: "y" }, { id: "z", name: "z" }] };
      }
      const m = p.match(/^api\/remote\/home\/album\/(\w)$/);
      if (m) return album(m[1]);
      throw new Error(`unmocked ${p}`);
    });
    const post = vi.fn().mockResolvedValue({ ok: true, count: 500, skipped: 0 });
    wrap(mockApi({ get, post }), ["artist", "big"]);
    fireEvent.click(await screen.findByRole("button", { name: "Play all" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const ids = (post.mock.calls[0][1] as { ids: string[] }).ids;
    expect(ids).toHaveLength(500);
    expect(ids[499]).toBe("y-199");
    expect(get).not.toHaveBeenCalledWith("api/remote/home/album/z");
    expect(await screen.findByText(/first 500 tracks of Prolific/)).toBeTruthy();
  });
});

describe("Music", () => {
  it("switches between the Home Library and this boombox's library", async () => {
    const navigate = vi.fn();
    const api = mockApi();
    render(<ApiProvider api={api}><Music params={[]} navigate={navigate} /></ApiProvider>);
    expect(await screen.findByText("Blue")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "On this boombox" }));
    expect(navigate).toHaveBeenCalledWith("music", ["boombox"]);
  });
});

const ALBUM_OFFLINE = { ...ALBUM, keep: { state: "kept", tracks_total: 3, tracks_present: 2 },
  tracks: [{ ...ALBUM.tracks[0], offline: true }, { ...ALBUM.tracks[1], offline: false },
           { ...ALBUM.tracks[2], offline: true }] };

function offlineApi(overrides: Partial<RemoteApi> = {}): RemoteApi {
  return mockApi({
    get: vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/home/status") return { online: false, internal_storage: true };
      if (p === "api/remote/home/offline") return { album_ids: ["al1"], artist_ids: ["ar1"], playlist_ids: [] };
      if (p === "api/remote/home/browse?type=albums") return ALBUMS;
      if (p === "api/remote/home/album/al1") return ALBUM_OFFLINE;
      if (p === "api/remote/home/album/al2") return { ...ALBUM2, tracks: [{ id: "t9", title: "Help Me", offline: false }] };
      throw new Error(`unmocked ${p}`);
    }),
    ...overrides,
  });
}

function albumApi(keep: object, extra: Partial<RemoteApi> = {}): RemoteApi {
  return mockApi({
    get: vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/home/album/al1") return { ...ALBUM, keep };
      throw new Error(`unmocked ${p}`);
    }),
    ...extra,
  });
}

describe("HomeLibrary offline + keep", () => {
  it("offline: banner, dimmed un-kept rows, Play all sends only kept tracks", async () => {
    const api = offlineApi();
    wrap(api, ["album", "al1"]);
    expect(await screen.findByText("Offline — showing kept music")).toBeTruthy();
    const row = (await screen.findByText("My Old Man")).closest("li")!;
    expect(row.textContent).toContain("not offline");
    expect((within(row).getByRole("button", { name: "Play from My Old Man" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Play all" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t1", "t3"], mode: "play" }));
  });

  it("offline: album tiles that aren't kept are dimmed", async () => {
    wrap(offlineApi(), []);
    await screen.findByText("Offline — showing kept music");
    await waitFor(() => expect(screen.getByRole("button", { name: /Court and Spark/ }).textContent)
      .toContain("not offline"));
    expect(screen.getByRole("button", { name: /^Blue/ }).textContent).not.toContain("not offline");
  });

  it("offline with nothing kept: says so without calling play", async () => {
    const api = offlineApi();
    wrap(api, ["album", "al2"]);
    await screen.findByText("Offline — showing kept music");
    await screen.findByText("Help Me");
    fireEvent.click(screen.getByRole("button", { name: "Play all" }));
    expect(await screen.findByText("None of these tracks are on the boombox.")).toBeTruthy();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("Keep offline pins the album and shows progress", async () => {
    const api = albumApi({ state: "none", tracks_total: 3, tracks_present: 0 }, {
      post: vi.fn().mockImplementation(async (p: string) => p === "api/remote/home/keep"
        ? { ok: true, queued: 3, keep: { state: "kept", tracks_total: 3, tracks_present: 0 } }
        : { ok: true, count: 3, skipped: 0 }),
    });
    wrap(api, ["album", "al1"]);
    const sw = await screen.findByRole("switch", { name: "Keep offline" });
    expect(sw.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(sw);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("api/remote/home/keep", { kind: "album", id: "al1" }));
    expect(await screen.findByText("0 / 3 on the boombox")).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Keep offline" }).getAttribute("aria-checked")).toBe("true");
  });

  it("a kept album can be removed with DELETE", async () => {
    const del = vi.fn().mockResolvedValue({ ok: true, cancelled: 0,
      keep: { state: "none", tracks_total: 3, tracks_present: 3 } });
    const api = albumApi({ state: "kept", tracks_total: 3, tracks_present: 3 }, { del });
    wrap(api, ["album", "al1"]);
    expect(await screen.findByText("All 3 on the boombox")).toBeTruthy();
    fireEvent.click(screen.getByRole("switch", { name: "Keep offline" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("api/remote/home/keep", { kind: "album", id: "al1" }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Keep offline" })
      .getAttribute("aria-checked")).toBe("false"));
  });

  it("a starred album says so and has no switch", async () => {
    wrap(albumApi({ state: "starred", tracks_total: 3, tracks_present: 2 }), ["album", "al1"]);
    expect(await screen.findByText(/Starred in Navidrome/)).toBeTruthy();
    expect(screen.getByText("2 / 3 on the boombox")).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("progress refreshes while a kept album downloads", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let calls = 0;
    const api = mockApi({
      get: vi.fn().mockImplementation(async (p: string) => {
        if (p === "api/remote/home/album/al1") {
          calls += 1;
          return { ...ALBUM, keep: { state: "kept", tracks_total: 3, tracks_present: calls === 1 ? 1 : 3 } };
        }
        throw new Error(`unmocked ${p}`);
      }),
    });
    wrap(api, ["album", "al1"]);
    expect(await screen.findByText("1 / 3 on the boombox")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(await screen.findByText("All 3 on the boombox")).toBeTruthy();
    vi.useRealTimers();
  });
});
