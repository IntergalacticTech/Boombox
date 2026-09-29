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
