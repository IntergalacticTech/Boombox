import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  browseHomeLibrary,
  capHomeTrackList,
  expandHomeRef,
  friendlyTrackTitle,
  homeSearchRefs,
  isLibraryStreamUri,
  parseHomeUri,
  playUris,
  queueUris,
  resolvePlayableUris,
  PlaybackUnavailableError,
  MAX_EXPANDED_TRACKS,
} from "../library";
import { subsonicIdFromUri } from "../favorites";

// Minimal fetch router: /mopidy/rpc calls are recorded; /api/library/* paths
// answer from `routes` (keyed "METHOD path"); anything else 404s.
type Rpc = { method: string; params: unknown };
let rpcCalls: Rpc[];
let libCalls: { key: string; body: unknown }[];
let routes: Record<string, unknown>;
// Per-method RPC results (default null). A function gets the params.
let rpcResults: Record<string, unknown>;

function json(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300, status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

beforeEach(() => {
  rpcCalls = [];
  libCalls = [];
  routes = {};
  rpcResults = {};
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (input === "/mopidy/rpc") {
      rpcCalls.push({ method: body.method, params: body.params });
      const r = rpcResults[body.method];
      const result = typeof r === "function" ? (r as (p: unknown) => unknown)(body.params) : (r ?? null);
      return json({ jsonrpc: "2.0", id: body.id, result });
    }
    const key = `${method} ${input}`;
    libCalls.push({ key, body });
    if (key in routes) {
      const r = routes[key];
      return json(typeof r === "function" ? (r as (b: unknown) => unknown)(body) : r);
    }
    return json({ error: "not found" }, 404);
  }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Resolver stub: ids in `offline` miss, the rest stream via the proxy. */
function stubResolve(offline: string[] = []) {
  routes["POST /api/library/resolve"] = (b: unknown) => ({
    items: (b as { ids: string[] }).ids.map(id => offline.includes(id)
      ? { id, source: "offline_miss", uri: null, cache_status: "absent" }
      : { id, source: "stream", uri: `http://127.0.0.1:6687/api/library/stream/${id}`, cache_status: "absent" }),
  });
}

describe("browseHomeLibrary drilldowns", () => {
  it("home:artist:X lists the artist's albums with art ids", async () => {
    routes["GET /api/library/artist/ar1"] = {
      artist: { id: "ar1", name: "Band", art_id: "ar-ar1" },
      albums: [
        { id: "al1", name: "First", year: 2001, art_id: "al-1" },
        { id: "al2", name: "Second", art_id: "al-2" },
      ],
    };
    const refs = await browseHomeLibrary("home:artist:ar1");
    expect(refs).toEqual([
      { uri: "home:album:al1", name: "First", type: "album", artId: "al-1" },
      { uri: "home:album:al2", name: "Second", type: "album", artId: "al-2" },
    ]);
  });

  it("home:album:X lists tracks as home:track refs with artist + ms duration", async () => {
    routes["GET /api/library/album/al1"] = {
      album: { id: "al1", name: "First", artist: "Band", art_id: "al-1" },
      tracks: [
        { id: "t1", title: "Intro", artist: "Band", track: 1, duration: 61 },
        { id: "t2", title: "Outro" },
      ],
    };
    const refs = await browseHomeLibrary("home:album:al1");
    expect(refs).toEqual([
      { uri: "home:track:t1", name: "Intro", type: "track", artist: "Band", lengthMs: 61000, artId: "al-1" },
      { uri: "home:track:t2", name: "Outro", type: "track", artist: undefined, lengthMs: undefined, artId: "al-1" },
    ]);
  });

  it("home:playlist:X lists its tracks", async () => {
    routes["GET /api/library/playlist/p1"] = {
      playlist: { id: "p1", name: "Mix" },
      tracks: [{ id: "t9", title: "Nine", artist: "X", duration: 200 }],
    };
    const refs = await browseHomeLibrary("home:playlist:p1");
    expect(refs.map(r => [r.uri, r.type, r.name])).toEqual([["home:track:t9", "track", "Nine"]]);
  });

  it("encodes ids in the drilldown path", async () => {
    routes["GET /api/library/album/a%2Fb"] = { album: { id: "a/b", name: "S" }, tracks: [] };
    expect(await browseHomeLibrary("home:album:a/b")).toEqual([]);
  });

  it("propagates backend errors so the drawer can show them", async () => {
    await expect(browseHomeLibrary("home:album:missing")).rejects.toThrow("not found");
  });
});

describe("parseHomeUri", () => {
  it("splits kind and id, keeping colons inside the id", () => {
    expect(parseHomeUri("home:album:x:y")).toEqual({ kind: "album", id: "x:y" });
    expect(parseHomeUri("home:root")).toBeNull();
    expect(parseHomeUri("local:track:1")).toBeNull();
  });
});

describe("resolvePlayableUris", () => {
  it("resolves home:track refs in one batch, preserving order and passing others through", async () => {
    stubResolve();
    const out = await resolvePlayableUris([
      "home:track:a", "local:track:x.mp3", "home:track:b",
    ]);
    expect(out).toEqual([
      "http://127.0.0.1:6687/api/library/stream/a",
      "local:track:x.mp3",
      "http://127.0.0.1:6687/api/library/stream/b",
    ]);
    const resolves = libCalls.filter(c => c.key === "POST /api/library/resolve");
    expect(resolves).toHaveLength(1);
    expect(resolves[0].body).toEqual({ ids: ["a", "b"] });
  });

  it("uses cached file:// URIs when the resolver returns them", async () => {
    routes["POST /api/library/resolve"] = {
      items: [{ id: "a", source: "cache", uri: "file:///mnt/cache/audio/a.flac", cache_status: "present" }],
    };
    expect(await resolvePlayableUris(["home:track:a"])).toEqual(["file:///mnt/cache/audio/a.flac"]);
  });

  it("drops offline_miss items and warns", async () => {
    stubResolve(["b"]);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const out = await resolvePlayableUris(["home:track:a", "home:track:b", "home:track:c"]);
    expect(out).toEqual([
      "http://127.0.0.1:6687/api/library/stream/a",
      "http://127.0.0.1:6687/api/library/stream/c",
    ]);
    expect(warn).toHaveBeenCalled();
  });

  it("throws PlaybackUnavailableError when nothing is playable", async () => {
    stubResolve(["a", "b"]);
    vi.spyOn(console, "warn").mockImplementation(() => {});
    await expect(resolvePlayableUris(["home:track:a", "home:track:b"]))
      .rejects.toBeInstanceOf(PlaybackUnavailableError);
  });

  it("does not call the resolver when there are no home refs", async () => {
    expect(await resolvePlayableUris(["local:track:1"])).toEqual(["local:track:1"]);
    expect(libCalls).toHaveLength(0);
  });
});

describe("playUris / queueUris", () => {
  it("playUris clears, starts the head, then appends the rest (resolved)", async () => {
    stubResolve();
    await playUris(["home:track:a", "home:track:b", "home:track:c"]);
    await vi.waitFor(() => expect(rpcCalls).toHaveLength(4));
    expect(rpcCalls.map(c => c.method)).toEqual([
      "core.tracklist.clear", "core.tracklist.add", "core.playback.play", "core.tracklist.add",
    ]);
    expect(rpcCalls[1].params).toEqual({ uris: ["http://127.0.0.1:6687/api/library/stream/a"] });
    expect(rpcCalls[3].params).toEqual({ uris: [
      "http://127.0.0.1:6687/api/library/stream/b",
      "http://127.0.0.1:6687/api/library/stream/c",
    ] });
  });

  it("playUris with one URI makes a single add", async () => {
    await playUris(["http://ice1.somafm.com/groovesalad-128-mp3"]);
    expect(rpcCalls.map(c => c.method)).toEqual([
      "core.tracklist.clear", "core.tracklist.add", "core.playback.play",
    ]);
  });

  it("playUris leaves the queue alone when every track is unplayable", async () => {
    stubResolve(["a"]);
    vi.spyOn(console, "warn").mockImplementation(() => {});
    await expect(playUris(["home:track:a"])).rejects.toThrow(/can't play/i);
    expect(rpcCalls).toHaveLength(0);
  });

  it("playUris tries the next head when the first fails to add", async () => {
    // Mopidy returns [] from tracklist.add when lookup fails (e.g. an
    // evicted cache file); "gone" never adds.
    rpcResults["core.tracklist.add"] = (p: unknown) =>
      (p as { uris: string[] }).uris.filter(u => u !== "file:///gone.flac").map((uri, i) => ({ tlid: i, track: { uri } }));
    await playUris(["file:///gone.flac", "local:track:2", "local:track:3"]);
    await vi.waitFor(() => expect(rpcCalls).toHaveLength(5));
    expect(rpcCalls.map(c => [c.method, c.params])).toEqual([
      ["core.tracklist.clear", {}],
      ["core.tracklist.add", { uris: ["file:///gone.flac"] }],
      ["core.tracklist.add", { uris: ["local:track:2"] }],
      ["core.playback.play", {}],
      ["core.tracklist.add", { uris: ["local:track:3"] }],
    ]);
  });

  it("playUris throws when nothing adds, without calling play", async () => {
    rpcResults["core.tracklist.add"] = [];
    await expect(playUris(["local:a", "local:b"])).rejects.toBeInstanceOf(PlaybackUnavailableError);
    expect(rpcCalls.map(c => c.method)).not.toContain("core.playback.play");
  });

  it("playUris appends a long tail in chunks without waiting for it", async () => {
    const uris = Array.from({ length: 26 }, (_, i) => `local:track:${i}`);
    let release!: () => void;
    const gate = new Promise<void>(r => { release = r; });
    let adds = 0;
    rpcResults["core.tracklist.add"] = () => [{ tlid: ++adds }];
    // Hold the first tail chunk: playUris must still resolve.
    const realFetch = globalThis.fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>;
    vi.stubGlobal("fetch", vi.fn(async (u: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      if (body.method === "core.tracklist.add" && adds >= 1) await gate;
      return realFetch(u, init);
    }));
    await playUris(uris);
    expect(rpcCalls.map(c => c.method)).toEqual([
      "core.tracklist.clear", "core.tracklist.add", "core.playback.play",
    ]);
    release();
    await vi.waitFor(() => expect(rpcCalls).toHaveLength(6));
    const tail = rpcCalls.slice(3).map(c => (c.params as { uris: string[] }).uris.length);
    expect(tail).toEqual([10, 10, 5]);
  });

  it("a newer playUris stops the older one's tail", async () => {
    let release!: () => void;
    const gate = new Promise<void>(r => { release = r; });
    let adds = 0;
    rpcResults["core.tracklist.add"] = () => [{ tlid: ++adds }];
    const realFetch = globalThis.fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>;
    vi.stubGlobal("fetch", vi.fn(async (u: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      // Hold the first request's first tail chunk.
      if (body.method === "core.tracklist.add" && adds === 1) { adds += 1; await gate; }
      return realFetch(u, init);
    }));
    const first = Array.from({ length: 25 }, (_, i) => `local:old:${i}`);
    await playUris(first);
    await playUris(["local:new:0", "local:new:1"]);
    release();
    await vi.waitFor(() => expect(rpcCalls.filter(c => c.method === "core.tracklist.add").length).toBeGreaterThanOrEqual(4));
    await new Promise(r => setTimeout(r, 20));
    const addedOld = rpcCalls
      .filter(c => c.method === "core.tracklist.add")
      .flatMap(c => (c.params as { uris: string[] }).uris)
      .filter(u => u.startsWith("local:old:"));
    // Head + the one chunk already in flight; the rest are dropped.
    expect(addedOld).toHaveLength(11);
  });

  it("queueUris resolves home refs before core.tracklist.add", async () => {
    stubResolve();
    await queueUris(["home:track:a", "local:track:z"]);
    expect(rpcCalls).toEqual([{ method: "core.tracklist.add", params: { uris: [
      "http://127.0.0.1:6687/api/library/stream/a", "local:track:z",
    ] } }]);
  });
});

describe("expandHomeRef", () => {
  it("expands an artist to every album's tracks in album order", async () => {
    routes["GET /api/library/artist/ar1"] = {
      artist: { id: "ar1", name: "Band" },
      albums: [{ id: "al1", name: "One" }, { id: "al2", name: "Two" }],
    };
    routes["GET /api/library/album/al1"] = { album: { id: "al1", name: "One" }, tracks: [{ id: "1", title: "a" }, { id: "2", title: "b" }] };
    routes["GET /api/library/album/al2"] = { album: { id: "al2", name: "Two" }, tracks: [{ id: "3", title: "c" }] };
    expect(await expandHomeRef({ uri: "home:artist:ar1" })).toEqual([
      "home:track:1", "home:track:2", "home:track:3",
    ]);
  });

  it("caps an artist at MAX_EXPANDED_TRACKS and stops fetching albums", async () => {
    const albums = Array.from({ length: 10 }, (_, i) => ({ id: `al${i}`, name: `A${i}` }));
    routes["GET /api/library/artist/big"] = { artist: { id: "big", name: "Big" }, albums };
    for (const al of albums) {
      routes[`GET /api/library/album/${al.id}`] = {
        album: al,
        tracks: Array.from({ length: 200 }, (_, j) => ({ id: `${al.id}-${j}`, title: "t" })),
      };
    }
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const uris = await expandHomeRef({ uri: "home:artist:big" });
    expect(uris).toHaveLength(MAX_EXPANDED_TRACKS);
    expect(uris[0]).toBe("home:track:al0-0");
    expect(warn).toHaveBeenCalled();
    // 3 albums (600 tracks) are enough to fill 500; the rest aren't fetched.
    expect(libCalls.filter(c => c.key.startsWith("GET /api/library/album/"))).toHaveLength(3);
  });

  it("expands an album and passes a track through", async () => {
    routes["GET /api/library/album/al1"] = { album: { id: "al1", name: "One" }, tracks: [{ id: "1", title: "a" }] };
    expect(await expandHomeRef({ uri: "home:album:al1" })).toEqual(["home:track:1"]);
    expect(await expandHomeRef({ uri: "home:track:7" })).toEqual(["home:track:7"]);
    expect(await expandHomeRef({ uri: "local:album:x" })).toEqual([]);
  });
});

describe("capHomeTrackList", () => {
  it("caps lists with home refs, leaves other sources alone", () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const home = Array.from({ length: 600 }, (_, i) => `home:track:${i}`);
    const local = Array.from({ length: 600 }, (_, i) => `local:track:${i}`);
    expect(capHomeTrackList(home)).toHaveLength(MAX_EXPANDED_TRACKS);
    expect(capHomeTrackList(local)).toHaveLength(600);
    expect(capHomeTrackList(home.slice(0, 3))).toEqual(home.slice(0, 3));
  });
});

describe("homeSearchRefs", () => {
  it("maps results to home refs grouped artist → album → track", () => {
    const refs = homeSearchRefs([
      { content_type: "track", id: "t1", title: "Song" },
      { content_type: "album", id: "al1", title: "Record" },
      { content_type: "artist", id: "ar1", title: "Band" },
      { content_type: "track", id: "t2", title: "Song 2" },
    ]);
    expect(refs).toEqual([
      { uri: "home:artist:ar1", name: "Band", type: "artist" },
      { uri: "home:album:al1", name: "Record", type: "album" },
      { uri: "home:track:t1", name: "Song", type: "track" },
      { uri: "home:track:t2", name: "Song 2", type: "track" },
    ]);
  });
});

describe("stream-proxy URI helpers", () => {
  it("isLibraryStreamUri matches loopback and relative proxy forms only", () => {
    expect(isLibraryStreamUri("http://127.0.0.1:6687/api/library/stream/abc")).toBe(true);
    expect(isLibraryStreamUri("http://127.0.0.1:6687/api/library/stream/abc?format=mp3")).toBe(true);
    expect(isLibraryStreamUri("/api/library/stream/abc")).toBe(true);
    expect(isLibraryStreamUri("http://ice1.somafm.com/groovesalad-128-mp3")).toBe(false);
    expect(isLibraryStreamUri("subsonic:track:1")).toBe(false);
    expect(isLibraryStreamUri(null)).toBe(false);
  });

  it("friendlyTrackTitle never returns a raw URL", () => {
    expect(friendlyTrackTitle("Real Title", "http://127.0.0.1:6687/api/library/stream/a")).toBe("Real Title");
    expect(friendlyTrackTitle("", "http://127.0.0.1:6687/api/library/stream/a?t=1")).toBe("Home Library track");
    expect(friendlyTrackTitle(
      "https://video.example/Audio/1/stream?api_key=secret", "https://video.example/Audio/1/stream?api_key=secret",
    )).toBe("Stream · video.example");
    expect(friendlyTrackTitle(undefined, "file:///media/usb/My%20Song.mp3")).toBe("My Song.mp3");
    expect(friendlyTrackTitle(undefined, undefined)).toBe("Unknown track");
  });

  it("subsonicIdFromUri recognises the stream proxy and home:track forms", () => {
    expect(subsonicIdFromUri("http://127.0.0.1:6687/api/library/stream/tr-42")).toBe("tr-42");
    expect(subsonicIdFromUri("http://127.0.0.1:6687/api/library/stream/tr-42?maxBitRate=320")).toBe("tr-42");
    expect(subsonicIdFromUri("/api/library/stream/a%20b")).toBe("a b");
    expect(subsonicIdFromUri("home:track:tr-7")).toBe("tr-7");
    expect(subsonicIdFromUri("subsonic:track:9")).toBe("9");
    expect(subsonicIdFromUri("file:///mnt/cache/audio/tr-1.flac")).toBe("tr-1");
    expect(subsonicIdFromUri("http://ice1.somafm.com/groovesalad-128-mp3")).toBeNull();
  });
});
