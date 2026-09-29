import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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
  });

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
