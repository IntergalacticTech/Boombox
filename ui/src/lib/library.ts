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
  /** Home Library track rows only: display artist + duration (ms). */
  artist?: string;
  lengthMs?: number;
  /** Home Library track rows only: the file is on the boombox. Undefined
   * when the server didn't say (treated as playable). */
  offline?: boolean;
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

/** How many leading URIs playUris tries one at a time before giving up on
 * a fast start and adding everything left in one batch. */
const HEAD_ATTEMPTS = 3;
/** Tail URIs per core.tracklist.add. Each stream URI costs Mopidy a scan
 * (an HTTP open through the proxy); small batches let pause/next/volume
 * RPCs slot in between instead of waiting out the whole list. */
const TAIL_CHUNK = 10;

// Bumped by every playUris call. A background tail append stops as soon as
// a newer request from this tab has replaced the queue, so two quick taps
// never merge. Replacements from elsewhere (RFID tap, boombox-resume, the
// phone remote, another tab) are caught by the tlid anchor in appendTail.
let playGeneration = 0;

type AddResult = {
  /** False only when Mopidy answered with an empty list (nothing added). */
  ok: boolean;
  /** tlids of the added TlTracks, in order (empty for a stubbed reply). */
  tlids: number[];
};

const isHttpUri = (u: string) => /^https?:\/\//i.test(u);

function tlidsOf(added: unknown): number[] {
  if (!Array.isArray(added)) return [];
  return added
    .map(t => (t && typeof t === "object" ? (t as { tlid?: unknown }).tlid : undefined))
    .filter((t): t is number => typeof t === "number");
}

/** core.tracklist.add returns the added TlTracks; an empty list means Mopidy
 * couldn't look the URI up (evicted cache file, missing local: track…).
 * Anything else (a stubbed null) counts as success.
 *
 * Mirrors the RFID client's _add: Mopidy 3.4.2 + recent GStreamer can drop
 * http(s) URIs at scan time and return []. Those are retried as Track
 * objects, which skip the scan since we supply the metadata ourselves. */
async function addUris(uris: string[], atPosition?: number): Promise<AddResult> {
  const withPos = (p: Record<string, unknown>) =>
    atPosition === undefined ? p : { ...p, at_position: atPosition };
  let added = await rpc<unknown>("core.tracklist.add", withPos({ uris }));
  if (Array.isArray(added) && added.length === 0) {
    const http = uris.filter(isHttpUri);
    if (http.length > 0) {
      const tracks = http.map(uri => ({ __model__: "Track", uri, name: "Streaming" }));
      added = await rpc<unknown>("core.tracklist.add", withPos({ tracks }));
    }
  }
  return { ok: !(Array.isArray(added) && added.length === 0), tlids: tlidsOf(added) };
}

/** Position of a tlid in the current tracklist, or null once it's gone. */
async function tlidIndex(tlid: number): Promise<number | null> {
  const idx = await rpc<unknown>("core.tracklist.index", { tlid });
  return typeof idx === "number" ? idx : null;
}

/** Queue `uris` in chunks, each placed right after the last track we added
 * (starting from the head's tlid) — the same contract as the RFID client's
 * append_tail and boombox-resume's append_restore_tail. If the anchor has
 * left the tracklist, somebody else replaced the queue and the rest of this
 * list belongs nowhere, so we stop; a chunk that was in flight when that
 * happened landed in the foreign queue and is removed again. With no anchor
 * (Mopidy returned no tlids) chunks are simply appended. */
async function appendTail(
  uris: string[], generation: number, headTlid: number | null,
): Promise<void> {
  let anchor = headTlid;
  for (let i = 0; i < uris.length; i += TAIL_CHUNK) {
    if (generation !== playGeneration) return;
    let at: number | undefined;
    if (anchor !== null) {
      const idx = await tlidIndex(anchor);
      if (idx === null) return;
      at = idx + 1;
    }
    const { tlids } = await addUris(uris.slice(i, i + TAIL_CHUNK), at);
    if (tlids.length === 0) continue;
    if (anchor !== null && (await tlidIndex(anchor)) === null) {
      // Replaced while this chunk was in flight: take it back out.
      await rpc("core.tracklist.remove", { criteria: { tlid: tlids } });
      return;
    }
    anchor = tlids[tlids.length - 1];
  }
}

/** Replace the current tracklist with the given URIs and start playing the first.
 *
 * home:track:<id> refs are resolved to cache/stream URIs first (see
 * resolvePlayableUris). The head track is added and started before the
 * rest are appended: Mopidy's stream backend scans every http URI on add,
 * so adding a whole album up front would delay the first note by N scans.
 * If a head URI fails to add, the next one is tried (up to HEAD_ATTEMPTS).
 *
 * Resolves once playback has started. The tail is appended in the
 * background, in chunks; the returned promise does not wait for it. */
export async function playUris(uris: string[]): Promise<void> {
  if (uris.length === 0) return;
  const playable = await resolvePlayableUris(uris);
  const generation = ++playGeneration;
  await rpc("core.tracklist.clear");
  let next = 0;
  let started = false;
  let headTlid: number | null = null;
  while (next < playable.length && next < HEAD_ATTEMPTS && !started) {
    const head = await addUris(playable.slice(next, next + 1));
    started = head.ok;
    headTlid = head.tlids[0] ?? null;
    next += 1;
  }
  if (!started) {
    // Every head we tried failed — add the remainder in one go and let
    // Mopidy start whichever of them did add.
    if (next >= playable.length || !(await addUris(playable.slice(next))).ok) {
      throw new PlaybackUnavailableError("Couldn't queue any of those tracks.");
    }
    next = playable.length;
  }
  // A newer playUris replaced the queue while our head was being scanned.
  if (generation !== playGeneration) return;
  await rpc("core.playback.play");
  const tail = playable.slice(next);
  if (tail.length > 0) {
    void appendTail(tail, generation, headTlid).catch(e => {
      console.warn("[library] failed to queue the rest of the tracks:", e);
    });
  }
}

/** Append URIs to the current tracklist without interrupting playback. */
export async function queueUris(uris: string[]): Promise<void> {
  if (uris.length === 0) return;
  const playable = await resolvePlayableUris(uris);
  await addUris(playable);
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

/** Home Library track ref prefix. These never reach Mopidy as-is —
 * playUris/queueUris swap them for a file:// (cache) or proxy stream URI. */
export const HOME_TRACK_PREFIX = "home:track:";

/** Upper bound on tracks queued by one "play artist" / "play all". */
export const MAX_EXPANDED_TRACKS = 500;

/** Thrown when every requested track resolved to offline_miss — the drawer
 * shows the message instead of silently doing nothing. */
export class PlaybackUnavailableError extends Error {
  constructor(message = "Can't play that right now — it isn't cached and the Home Library server is unreachable.") {
    super(message);
    this.name = "PlaybackUnavailableError";
  }
}

/** Split a home:<kind>:<id> URI. Ids may themselves contain colons. */
export function parseHomeUri(uri: string): { kind: string; id: string } | null {
  if (!uri.startsWith("home:")) return null;
  const colon = uri.indexOf(":", 5);
  if (colon === -1) return null;
  return { kind: uri.slice(5, colon), id: uri.slice(colon + 1) };
}

/** Swap every home:track:<id> for its playable URI via ONE POST /resolve.
 * Order is preserved; offline_miss / uri-less items are dropped. Other URIs
 * (local:, file://, radio streams…) pass through untouched. Throws
 * PlaybackUnavailableError when nothing playable is left. */
export async function resolvePlayableUris(uris: string[]): Promise<string[]> {
  const ids = uris
    .filter(u => u.startsWith(HOME_TRACK_PREFIX))
    .map(u => u.slice(HOME_TRACK_PREFIX.length));
  if (ids.length === 0) return uris;

  const items = await libraryApi.resolveTracks(ids);
  const byId = new Map<string, string>();
  for (const it of items) {
    if (it && it.source !== "offline_miss" && it.uri) byId.set(it.id, it.uri);
  }
  const out: string[] = [];
  let dropped = 0;
  for (const u of uris) {
    if (!u.startsWith(HOME_TRACK_PREFIX)) { out.push(u); continue; }
    const resolved = byId.get(u.slice(HOME_TRACK_PREFIX.length));
    if (resolved) out.push(resolved); else dropped += 1;
  }
  if (dropped > 0) {
    console.warn(`[library] skipped ${dropped} of ${ids.length} Home Library track(s): not cached and not streamable`);
  }
  if (out.length === 0) {
    throw new PlaybackUnavailableError(ids.length > 1
      ? `None of these ${ids.length} tracks can play right now — they aren't cached and the Home Library server is unreachable.`
      : undefined);
  }
  return out;
}

function homeTrackRef(t: libraryApi.LibraryTrack, artId?: string): Ref {
  return {
    uri: `${HOME_TRACK_PREFIX}${t.id}`,
    name: t.title,
    type: "track",
    artist: t.artist || undefined,
    lengthMs: t.duration ? t.duration * 1000 : undefined,
    artId,
    // Older payloads carry only cache_status.
    offline: t.offline ?? (t.cache_status === undefined ? undefined : t.cache_status === "present"),
  };
}

function homeAlbumRef(a: { id: string; name: string; art_id?: string }): Ref {
  return { uri: `home:album:${a.id}`, name: a.name, type: "album", artId: a.art_id };
}

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
    return items.map(homeAlbumRef);
  }
  if (uri === "home:playlists") {
    const items = await libraryApi.browse("playlists");
    return items.map(p => ({
      uri: `home:playlist:${p.id}`, name: p.name, type: "playlist" as const,
    }));
  }
  const parsed = parseHomeUri(uri);
  if (parsed?.kind === "artist") {
    const { albums } = await libraryApi.getArtist(parsed.id);
    return albums.map(homeAlbumRef);
  }
  if (parsed?.kind === "album") {
    // Track rows borrow the album's cover so the list isn't a wall of glyphs.
    const { album, tracks } = await libraryApi.getAlbum(parsed.id);
    return tracks.map(t => homeTrackRef(t, album.art_id));
  }
  if (parsed?.kind === "playlist") {
    const { tracks } = await libraryApi.getPlaylist(parsed.id);
    return tracks.map(t => homeTrackRef(t));
  }
  return [];
}

/** Flatten a Home Library ref into ordered home:track: refs (with their
 * `offline` flags) — album and playlist in listed order, artist as every
 * album's tracks in the order /artist/<id> lists the albums. Capped at
 * MAX_EXPANDED_TRACKS. */
export async function expandHomeTracks(ref: Pick<Ref, "uri"> & Partial<Ref>): Promise<Ref[]> {
  const parsed = parseHomeUri(ref.uri);
  if (!parsed) return [];
  let refs: Ref[] = [];
  if (parsed.kind === "track") {
    refs = [{ name: "", type: "track", ...ref }];
  } else if (parsed.kind === "album" || parsed.kind === "playlist") {
    refs = await browseHomeLibrary(ref.uri);
  } else if (parsed.kind === "artist") {
    const { albums } = await libraryApi.getArtist(parsed.id);
    for (const al of albums) {
      // One more album than needed is enough to know we're truncating.
      if (refs.length > MAX_EXPANDED_TRACKS) break;
      const { tracks } = await libraryApi.getAlbum(al.id);
      refs.push(...tracks.map(t => homeTrackRef(t)));
    }
  }
  if (refs.length > MAX_EXPANDED_TRACKS) {
    console.warn(`[library] ${ref.uri}: queueing the first ${MAX_EXPANDED_TRACKS} tracks only`);
    refs = refs.slice(0, MAX_EXPANDED_TRACKS);
  }
  return refs;
}

/** expandHomeTracks as plain home:track: URIs. */
export async function expandHomeRef(ref: Pick<Ref, "uri">): Promise<string[]> {
  return (await expandHomeTracks(ref)).map(r => r.uri);
}

/** Trim a track list that contains Home Library refs to MAX_EXPANDED_TRACKS
 * (a big Navidrome playlist would otherwise mean thousands of resolves and
 * stream scans). Lists without home refs — local, radio — are untouched. */
export function capHomeTrackList(uris: string[]): string[] {
  if (uris.length <= MAX_EXPANDED_TRACKS) return uris;
  if (!uris.some(u => u.startsWith(HOME_TRACK_PREFIX))) return uris;
  console.warn(`[library] queueing the first ${MAX_EXPANDED_TRACKS} of ${uris.length} tracks`);
  return uris.slice(0, MAX_EXPANDED_TRACKS);
}

/** Map /api/library/search hits to home:* refs, grouped artists → albums →
 * tracks (server order kept within each group). */
export function homeSearchRefs(results: libraryApi.SearchResult[]): Ref[] {
  const rank: Record<string, number> = { artist: 0, album: 1, track: 2 };
  return results
    .filter(r => r.content_type in rank)
    .map((r, i) => ({ r, i }))
    .sort((a, b) => rank[a.r.content_type] - rank[b.r.content_type] || a.i - b.i)
    .map(({ r }) => ({
      uri: r.content_type === "track"
        ? `${HOME_TRACK_PREFIX}${r.id}`
        : `home:${r.content_type}:${r.id}`,
      name: r.title,
      type: r.content_type,
      // Albums / artists are dimmed from GET /offline instead (fails open).
      ...(r.content_type === "track" && r.offline !== undefined ? { offline: r.offline } : {}),
    }));
}

export async function searchHomeLibrary(query: string): Promise<Ref[]> {
  return homeSearchRefs(await libraryApi.search(query));
}

/** True for URIs served by the boombox-library stream proxy — the loopback
 * form Mopidy plays (http://127.0.0.1:6687/api/library/stream/<id>) or the
 * nginx-relative /api/library/stream/<id>. */
export function isLibraryStreamUri(uri: string | null | undefined): boolean {
  return !!uri && /^(?:https?:\/\/[^/]+)?\/api\/library\/stream\/[^/?#]+/i.test(uri);
}

/** A display title that never leaks a raw URL (proxy stream URIs, links with
 * api keys in the query string…) onto the screen. Mopidy's stream backend
 * leaves Track.name empty when the file carries no title tag. */
export function friendlyTrackTitle(
  name: string | null | undefined, uri: string | null | undefined,
): string {
  const looksLikeUrl = (s: string) => /^[a-z][a-z0-9+.-]*:\/\//i.test(s);
  if (name && !looksLikeUrl(name)) return name;
  const u = uri || name || "";
  if (isLibraryStreamUri(u)) return "Home Library track";
  if (u.startsWith("file://")) {
    const base = decodeURIComponent(u).split("/").pop() ?? "";
    return base || "Local file";
  }
  if (/^https?:\/\//i.test(u)) {
    try { return `Stream · ${new URL(u).hostname}`; } catch { return "Stream"; }
  }
  return u || "Unknown track";
}
