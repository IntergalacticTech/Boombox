// library.ts — thin wrappers over Mopidy's `core.library.*` and tracklist RPCs.
//
// Uses HTTP JSON-RPC (POST /mopidy/rpc) for one-off calls. The WebSocket client
// in mopidy.ts is for state subscriptions; for fire-and-forget browse/queue
// actions, plain fetch is simpler and lets us drop the Promise plumbing.

export type Ref = {
  uri: string;
  name: string;
  type: "directory" | "album" | "artist" | "track" | "playlist";
  /** Subsonic cover-art id. Present on Home Library rows (Navidrome-backed);
   * absent on legacy Mopidy-Local rows. AlbumThumb uses it to hit the local
   * art proxy at /api/library/art/<id> instead of iTunes Search. */
  artId?: string;
};

export type MopidyTrack = {
  uri: string;
  name: string;
  artists?: { name?: string }[];
  album?: { name?: string; uri?: string };
  length?: number;
  track_no?: number;
  date?: string;
};

export type MopidyImage = { uri: string; width?: number; height?: number };

let nextId = 1;

async function rpc<T>(method: string, params?: Record<string, unknown> | unknown[]): Promise<T> {
  const r = await fetch("/mopidy/rpc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: nextId++, method, params: params ?? {} }),
  });
  if (!r.ok) throw new Error(`mopidy rpc ${method} → ${r.status}`);
  const j = await r.json();
  if (j.error) throw new Error(`mopidy rpc ${method} error: ${JSON.stringify(j.error)}`);
  return j.result as T;
}

/** List children of a Mopidy URI ("local:directory?type=album", album URI, etc.) */
export function browse(uri: string | null): Promise<Ref[]> {
  return rpc<Ref[]>("core.library.browse", { uri });
}

/** Resolve metadata for one or more URIs. Returns map of uri → tracks[]. */
export function lookup(uris: string[]): Promise<Record<string, MopidyTrack[]>> {
  return rpc<Record<string, MopidyTrack[]>>("core.library.lookup", { uris });
}

export type SearchResult = {
  uri: string;
  tracks?: MopidyTrack[];
  albums?: { uri: string; name: string; date?: string; artists?: { name?: string }[] }[];
  artists?: { uri: string; name: string }[];
};

/** Free-text search across the library. Mopidy returns one result per backend;
 * we just merge their track lists (good enough for a single local backend). */
export async function search(query: string): Promise<MopidyTrack[]> {
  if (!query.trim()) return [];
  const results = await rpc<SearchResult[]>("core.library.search", {
    query: { any: [query] },
  });
  return results.flatMap(r => r.tracks ?? []);
}

/** Cover-art / artwork lookup for a URI (album or track). */
export function getImages(uris: string[]): Promise<Record<string, MopidyImage[]>> {
  return rpc<Record<string, MopidyImage[]>>("core.library.get_images", { uris });
}

/** Replace the current tracklist with the given URIs and start playing the first. */
export async function playUris(uris: string[]): Promise<void> {
  if (uris.length === 0) return;
  await rpc("core.tracklist.clear");
  await rpc("core.tracklist.add", { uris });
  await rpc("core.playback.play");
}

/** Append URIs to the current tracklist without interrupting playback. */
export async function queueUris(uris: string[]): Promise<void> {
  if (uris.length === 0) return;
  await rpc("core.tracklist.add", { uris });
}

export type TlTrack = { tlid: number; track: MopidyTrack };

/** The current Mopidy queue (TlTracks have stable tlids we can pass to play/remove). */
export function getQueue(): Promise<TlTrack[]> {
  return rpc<TlTrack[]>("core.tracklist.get_tl_tracks");
}

/** Jump to a specific tlid and start playing it. */
export async function playTlid(tlid: number): Promise<void> {
  // core.playback.play accepts a TlTrack (object) — pass it as { tl_track }.
  // Simpler: change current via core.playback.play with `tlid` only since
  // Mopidy 3.x. The `tl_track` arg form is also supported.
  await rpc("core.playback.play", { tlid });
}

/** Remove a track from the queue by tlid. */
export async function removeTlid(tlid: number): Promise<void> {
  await rpc("core.tracklist.remove", { criteria: { tlid: [tlid] } });
}

/** Get the currently-playing TlTrack (or null when stopped). */
export function getCurrentTlid(): Promise<number | null> {
  return rpc<number | null>("core.playback.get_current_tlid");
}

/** Standard top-level browsing roots that the touchscreen UI offers. */
export const ROOTS: Ref[] = [
  { uri: "boombox:favorites",           name: "Favorites",    type: "directory" },
  { uri: "boombox:recent",              name: "Recent",       type: "directory" },
  { uri: "home:root",                   name: "Home Library", type: "directory" },
  { uri: "boombox:radio",               name: "Radio",        type: "directory" },
  { uri: "local:directory?type=album",  name: "Albums",       type: "directory" },
  { uri: "local:directory?type=artist", name: "Artists",      type: "directory" },
  { uri: "local:directory?type=track",  name: "Tracks",       type: "directory" },
];

/** Curated internet radio stations. Direct MP3/AAC streams that work via
 * Mopidy's Stream backend without M3U/PLS resolution. Add to / customise
 * here without touching anything else. */
export type RadioStation = {
  id: string;
  name: string;
  blurb: string;
  stream: string;
  accent: string;
};

export const RADIO_STATIONS: RadioStation[] = [
  {
    id: "somafm-groove",
    name: "Groove Salad",
    blurb: "SomaFM · downtempo / chillout",
    stream: "http://ice1.somafm.com/groovesalad-128-mp3",
    accent: "#5be7ff",
  },
  {
    id: "somafm-drone",
    name: "Drone Zone",
    blurb: "SomaFM · ambient drone",
    stream: "http://ice1.somafm.com/dronezone-128-mp3",
    accent: "#b794ff",
  },
  {
    id: "somafm-indie",
    name: "Indie Pop Rocks",
    blurb: "SomaFM · indie / college rock",
    stream: "http://ice1.somafm.com/indiepop-128-mp3",
    accent: "#ff7a35",
  },
  {
    id: "somafm-deep-space-one",
    name: "Deep Space One",
    blurb: "SomaFM · deep ambient electronic",
    stream: "http://ice1.somafm.com/deepspaceone-128-mp3",
    accent: "#1ed760",
  },
  {
    id: "kexp",
    name: "KEXP 90.3",
    blurb: "Seattle public radio · eclectic",
    stream: "https://kexp-mp3-128.streamguys1.com/kexp128.mp3",
    accent: "#ffd400",
  },
  {
    id: "bbc6",
    name: "BBC 6 Music",
    blurb: "BBC · alternative",
    stream: "http://stream.live.vc.bbcmedia.co.uk/bbc_6music",
    accent: "#ff2d8a",
  },
  {
    id: "bbc1",
    name: "BBC Radio 1",
    blurb: "BBC · pop / dance",
    stream: "http://stream.live.vc.bbcmedia.co.uk/bbc_radio_one",
    accent: "#5b9aff",
  },
  {
    id: "wfmu",
    name: "WFMU",
    blurb: "Jersey freeform · anything goes",
    stream: "https://stream0.wfmu.org/freeform-128k",
    accent: "#c8e44a",
  },
];

/** Mopidy's playback history — pairs of (epoch ms, Ref). */
export type HistoryEntry = { ts: number; ref: Ref };

export async function getHistory(): Promise<HistoryEntry[]> {
  const raw = await rpc<Array<[number, Ref]>>("core.history.get_history");
  return (raw ?? []).map(([ts, ref]) => ({ ts, ref }));
}

// ---- Home Library (Phase 2) ---------------------------------------------
//
// Home Library URIs are the boombox's parallel browse tree backed by the
// Phase 1 service at /api/library/*. They never round-trip through Mopidy's
// core.library.browse — instead browseHomeLibrary() translates each
// home:* URI into the matching libraryApi call.

import * as libraryApi from "./libraryApi";

export async function browseHomeLibrary(uri: string): Promise<Ref[]> {
  if (uri === "home:root") {
    return [
      { uri: "home:artists",     name: "Artists",     type: "directory" },
      { uri: "home:albums",      name: "Albums",      type: "directory" },
      { uri: "home:playlists",   name: "Playlists",   type: "directory" },
      { uri: "home:cached-only", name: "Cached only", type: "directory" },
    ];
  }
  if (uri === "home:artists") {
    const items = await libraryApi.browse("artists");
    return items.map(a => ({
      uri: `home:artist:${a.id}`, name: a.name, type: "artist" as const,
      artId: a.art_id,
    }));
  }
  if (uri === "home:albums" || uri === "home:cached-only") {
    // Cached-only filter is enforced row-side by the StatusBadge / cache poll
    // in Phase 2; a dedicated server-side filter lands in Phase 3.
    const items = await libraryApi.browse("albums");
    return items.map(a => ({
      uri: `home:album:${a.id}`, name: a.name, type: "album" as const,
      artId: a.art_id,
    }));
  }
  if (uri === "home:playlists") {
    const items = await libraryApi.browse("playlists");
    return items.map(p => ({
      uri: `home:playlist:${p.id}`, name: p.name, type: "playlist" as const,
    }));
  }
  // Deeper drilldowns (home:album:X / home:artist:X) need dedicated
  // /album/<id> / /artist/<id> endpoints — Phase 1 didn't ship them, so
  // for v1 we leave drilldown empty rather than throwing.
  return [];
}
