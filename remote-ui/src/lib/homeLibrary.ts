// Client for /api/remote/home/* — the Home Library (Navidrome, via
// boombox-library) as seen through boombox-remote's pair-token routes.
import type { RemoteApi } from "./api";

export type HomeList = "artists" | "albums" | "playlists";
export type HomeKind = "artist" | "album" | "playlist";

export interface HomeItem {
  id: string; name: string; artist_id?: string | null; year?: number | null;
  album_count?: number | null; song_count?: number | null; art_id?: string | null;
}
export interface HomeTrack {
  id: string; title: string; artist?: string | null; duration?: number | null;
  cache_status?: string;
}
export interface HomeAlbumDetail {
  album: { id: string; name: string; artist?: string | null; year?: number | null;
           art_id?: string | null };
  tracks: HomeTrack[];
}
export interface HomeArtistDetail {
  artist: { id: string; name: string; art_id?: string | null };
  albums: { id: string; name: string; year?: number | null; art_id?: string | null }[];
}
export interface HomePlaylistDetail { playlist: { id: string; name: string }; tracks: HomeTrack[] }
export interface HomeSearchResult { content_type: string; id: string; title: string }
export interface PlayResult { ok: boolean; count: number; skipped: number }

/** Cap for one "play artist", as on the kiosk. */
export const MAX_EXPANDED_TRACKS = 500;

// The albums list is ~700 KB for 8.7k albums; keep it for the session so
// moving between tabs and details doesn't refetch it.
const listCache = new Map<HomeList, HomeItem[]>();

export async function browseHome(api: RemoteApi, list: HomeList): Promise<HomeItem[]> {
  const hit = listCache.get(list);
  if (hit) return hit;
  const r = await api.get<{ items?: HomeItem[] }>(`api/remote/home/browse?type=${list}`);
  const items = Array.isArray(r.items) ? r.items : [];
  listCache.set(list, items);
  return items;
}

export function clearHomeCache(): void {
  listCache.clear();
}

export async function searchHome(api: RemoteApi, q: string): Promise<HomeSearchResult[]> {
  const r = await api.get<{ results?: HomeSearchResult[] }>(
    `api/remote/home/search?q=${encodeURIComponent(q)}`);
  return Array.isArray(r.results) ? r.results : [];
}

export function homeDetail<T>(api: RemoteApi, kind: HomeKind, id: string): Promise<T> {
  return api.get<T>(`api/remote/home/${kind}/${encodeURIComponent(id)}`);
}

export function playHome(api: RemoteApi, ids: string[], mode: "play" | "queue"): Promise<PlayResult> {
  return api.post<PlayResult>("api/remote/home/play", { ids, mode });
}

/** Every track of an artist, album by album in the order the library lists
 *  them, capped at MAX_EXPANDED_TRACKS. */
export async function artistTrackIds(api: RemoteApi, artistId: string): Promise<string[]> {
  const a = await homeDetail<HomeArtistDetail>(api, "artist", artistId);
  const ids: string[] = [];
  for (const al of a.albums) {
    if (ids.length >= MAX_EXPANDED_TRACKS) break;
    const d = await homeDetail<HomeAlbumDetail>(api, "album", al.id);
    ids.push(...d.tracks.map((t) => t.id));
  }
  return ids.slice(0, MAX_EXPANDED_TRACKS);
}

export function artPath(artId: string | null | undefined, size = 320): string | null {
  return artId ? `api/remote/home/art/${encodeURIComponent(artId)}?size=${size}` : null;
}
