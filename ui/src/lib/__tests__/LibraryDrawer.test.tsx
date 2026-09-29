import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import { LibraryDrawer } from "../LibraryDrawer";

// Same routing idea as library.test.ts: Mopidy JSON-RPC is recorded,
// /api/library/* answers from `routes`, everything else (art lookups) 404s.
let rpcMethods: { method: string; params: unknown }[];
let libCalls: string[];
let routes: Record<string, unknown>;

function json(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300, status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

class NoopIO {
  observe() {}
  disconnect() {}
  unobserve() {}
}

beforeEach(() => {
  rpcMethods = [];
  libCalls = [];
  routes = {
    "GET /api/library/browse?type=albums": { items: [{ id: "al1", name: "Record", art_id: "al-1" }] },
    "GET /api/library/browse?type=artists": { items: [{ id: "ar1", name: "Band" }] },
    "GET /api/library/album/al1": {
      album: { id: "al1", name: "Record", artist: "Band", art_id: "al-1" },
      tracks: [
        { id: "t1", title: "Side A", artist: "Band", duration: 125 },
        { id: "t2", title: "Side B", artist: "Band", duration: 90 },
      ],
    },
    "GET /api/library/artist/ar1": {
      artist: { id: "ar1", name: "Band" },
      albums: [{ id: "al1", name: "Record", art_id: "al-1" }],
    },
  };
  vi.stubGlobal("IntersectionObserver", NoopIO);
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (input === "/mopidy/rpc") {
      rpcMethods.push({ method: body.method, params: body.params });
      // tracklist.add answers with the added TlTracks; an empty list would
      // tell playUris the head failed to add.
      // The head sits at index 0, so the tail's anchor is always present.
      const result = body.method === "core.tracklist.add"
        ? (body.params.uris as string[]).map((uri, i) => ({ tlid: i + 1, track: { uri } }))
        : body.method === "core.tracklist.index" ? 0 : [];
      return json({ jsonrpc: "2.0", id: body.id, result });
    }
    const key = `${method} ${input}`;
    libCalls.push(key);
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

function streamAll() {
  routes["POST /api/library/resolve"] = (b: unknown) => ({
    items: (b as { ids: string[] }).ids.map(id => ({
      id, source: "stream", uri: `http://127.0.0.1:6687/api/library/stream/${id}`, cache_status: "absent",
    })),
  });
}

async function openAlbum(utils: ReturnType<typeof render>) {
  fireEvent.click(await utils.findByText("Home Library"));
  fireEvent.click(await utils.findByText("Albums"));
  fireEvent.click(await utils.findByText("Record"));
  // useIncrementalRender re-caps its slice one render after the list
  // length changes, so wait for the LAST row, not just the first.
  await utils.findByText("Side B");
}

describe("LibraryDrawer · Home Library", () => {
  it("drills into an album and shows track rows with artist + duration", async () => {
    const utils = render(<LibraryDrawer onClose={() => {}} />);
    await openAlbum(utils);
    expect(utils.getByText("Side A")).toBeInTheDocument();
    expect(utils.getByText("2:05")).toBeInTheDocument();
    expect(utils.getAllByText("Band").length).toBeGreaterThan(0);
    expect(utils.getByText(/PLAY ALL \(2\)/)).toBeInTheDocument();
  });

  it("tapping a track resolves and plays from that track onward", async () => {
    streamAll();
    const onClose = vi.fn();
    const utils = render(<LibraryDrawer onClose={onClose} />);
    await openAlbum(utils);
    fireEvent.click(utils.getByText("Side A"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    // The tail is appended in the background after the drawer closes.
    const adds = () => rpcMethods.filter(c => c.method === "core.tracklist.add").map(c => c.params);
    await waitFor(() => expect(adds()).toHaveLength(2));
    expect(adds()).toEqual([
      { uris: ["http://127.0.0.1:6687/api/library/stream/t1"] },
      { uris: ["http://127.0.0.1:6687/api/library/stream/t2"], at_position: 1 },
    ]);
    expect(libCalls.filter(k => k === "POST /api/library/resolve")).toHaveLength(1);
  });

  it("shows an inline error and stays open when nothing is playable", async () => {
    routes["POST /api/library/resolve"] = (b: unknown) => ({
      items: (b as { ids: string[] }).ids.map(id => ({ id, source: "offline_miss", uri: null, cache_status: "absent" })),
    });
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const onClose = vi.fn();
    const utils = render(<LibraryDrawer onClose={onClose} />);
    await openAlbum(utils);
    fireEvent.click(utils.getByText(/PLAY ALL/));
    const alert = await utils.findByRole("alert");
    expect(alert.textContent).toMatch(/None of these 2 tracks/);
    expect(onClose).not.toHaveBeenCalled();
    expect(rpcMethods.some(c => c.method === "core.tracklist.add")).toBe(false);
  });

  it("Play all on an artist page plays every album's tracks", async () => {
    streamAll();
    const onClose = vi.fn();
    const utils = render(<LibraryDrawer onClose={onClose} />);
    fireEvent.click(await utils.findByText("Home Library"));
    fireEvent.click(await utils.findByText("Artists"));
    fireEvent.click(await utils.findByText("Band"));
    await utils.findByText("Record");
    fireEvent.click(utils.getByText("▶ PLAY ALL"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const adds = () => rpcMethods.filter(c => c.method === "core.tracklist.add").flatMap(
      c => (c.params as { uris: string[] }).uris,
    );
    await waitFor(() => expect(adds()).toHaveLength(2));
    expect(adds()).toEqual([
      "http://127.0.0.1:6687/api/library/stream/t1",
      "http://127.0.0.1:6687/api/library/stream/t2",
    ]);
  });

  it("the album quick-play button expands the album", async () => {
    streamAll();
    const onClose = vi.fn();
    const utils = render(<LibraryDrawer onClose={onClose} />);
    fireEvent.click(await utils.findByText("Home Library"));
    fireEvent.click(await utils.findByText("Albums"));
    fireEvent.click(await utils.findByLabelText("Play Record"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(rpcMethods.map(c => c.method)).toContain("core.playback.play");
  });

  it("searching inside Home Library hits /api/library/search, not Mopidy", async () => {
    routes["GET /api/library/search?q=side"] = {
      results: [
        { content_type: "track", id: "t2", title: "Side B" },
        { content_type: "album", id: "al1", title: "Record" },
      ],
    };
    streamAll();
    const onClose = vi.fn();
    const utils = render(<LibraryDrawer onClose={onClose} />);
    fireEvent.click(await utils.findByText("Home Library"));
    await utils.findByText("Artists");
    fireEvent.change(utils.getByPlaceholderText("Search library…"), { target: { value: "side" } });
    await utils.findByText("Side B");
    expect(rpcMethods.some(c => c.method === "core.library.search")).toBe(false);
    fireEvent.click(utils.getByText("Side B"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(rpcMethods.find(c => c.method === "core.tracklist.add")?.params).toEqual({
      uris: ["http://127.0.0.1:6687/api/library/stream/t2"],
    });
  });

  it("opening an album search hit leaves search and lists its tracks", async () => {
    routes["GET /api/library/search?q=rec"] = {
      results: [{ content_type: "album", id: "al1", title: "Record" }],
    };
    const utils = render(<LibraryDrawer onClose={() => {}} />);
    fireEvent.click(await utils.findByText("Home Library"));
    await utils.findByText("Artists");
    const box = utils.getByPlaceholderText("Search library…") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "rec" } });
    fireEvent.click(await utils.findByText("Record"));
    await utils.findByText("Side B");
    expect(utils.getByText("Side A")).toBeInTheDocument();
    expect(libCalls).toContain("GET /api/library/album/al1");
    expect(box.value).toBe("");
    // One Back returns to the level the search started from.
    fireEvent.click(utils.getByText("‹ Back"));
    await utils.findByText("Artists");
  });

  it("a failed Home Library search reports an error, not 'No matches'", async () => {
    // No route for /api/library/search → 404.
    const utils = render(<LibraryDrawer onClose={() => {}} />);
    fireEvent.click(await utils.findByText("Home Library"));
    await utils.findByText("Artists");
    fireEvent.change(utils.getByPlaceholderText("Search library…"), { target: { value: "zzz" } });
    expect(await utils.findByText(/Library search failed/)).toBeInTheDocument();
    expect(utils.queryByText(/No matches/)).toBeNull();
  });

  it("ignores extra play taps while a request is in flight", async () => {
    let release!: () => void;
    const gate = new Promise<void>(r => { release = r; });
    routes["POST /api/library/resolve"] = async (b: unknown) => {
      await gate;
      return {
        items: (b as { ids: string[] }).ids.map(id => ({
          id, source: "stream", uri: `http://127.0.0.1:6687/api/library/stream/${id}`, cache_status: "absent",
        })),
      };
    };
    const onClose = vi.fn();
    const utils = render(<LibraryDrawer onClose={onClose} />);
    await openAlbum(utils);
    fireEvent.click(utils.getByText("Side A"));
    fireEvent.click(utils.getByText("Side B"));
    fireEvent.click(utils.getByText(/PLAY ALL/));
    release();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(libCalls.filter(k => k === "POST /api/library/resolve")).toHaveLength(1);
    expect(rpcMethods.filter(c => c.method === "core.tracklist.clear")).toHaveLength(1);
  });

  it("searching outside Home Library still uses Mopidy", async () => {
    const utils = render(<LibraryDrawer onClose={() => {}} />);
    fireEvent.change(utils.getByPlaceholderText("Search library…"), { target: { value: "x" } });
    await waitFor(() => expect(rpcMethods.some(c => c.method === "core.library.search")).toBe(true));
    expect(libCalls.some(k => k.includes("/api/library/search"))).toBe(false);
  });

  // Album / artist / playlist rows bind on tap in bind mode, so track rows
  // inside a drilldown are unreachable there — search hits are the only way
  // to bind a single track (covered by the next test).
  it("bind mode: tapping a home album tile binds the album instead of playing", async () => {
    const onTarget = vi.fn();
    const handler = (e: Event) => onTarget((e as CustomEvent).detail);
    window.addEventListener("boombox:rfid-bind-target", handler);
    try {
      const utils = render(<LibraryDrawer onClose={() => {}} bindUid="04aabbccdd" />);
      fireEvent.click(await utils.findByText("Albums"));
      // Albums render as a grid; tapping one in bind mode binds the album.
      fireEvent.click(await utils.findByText("Record"));
      expect(onTarget).toHaveBeenCalledWith({ kind: "album", id: "al1", label: "Record" });
      expect(rpcMethods).toHaveLength(0);
      expect(libCalls).not.toContain("POST /api/library/resolve");
    } finally {
      window.removeEventListener("boombox:rfid-bind-target", handler);
    }
  });

  it("bind mode: a track search hit binds as kind=track", async () => {
    routes["GET /api/library/search?q=side"] = {
      results: [{ content_type: "track", id: "t2", title: "Side B" }],
    };
    const onTarget = vi.fn();
    const handler = (e: Event) => onTarget((e as CustomEvent).detail);
    window.addEventListener("boombox:rfid-bind-target", handler);
    try {
      const utils = render(<LibraryDrawer onClose={() => {}} bindUid="04aabbccdd" />);
      await utils.findByText("Albums");
      fireEvent.change(utils.getByPlaceholderText("Search library…"), { target: { value: "side" } });
      fireEvent.click(await utils.findByText("Side B"));
      expect(onTarget).toHaveBeenCalledWith({ kind: "track", id: "t2", label: "Side B" });
      expect(libCalls).not.toContain("POST /api/library/resolve");
    } finally {
      window.removeEventListener("boombox:rfid-bind-target", handler);
    }
  });
});
