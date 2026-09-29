// Types + helpers for /api/remote/video/* (see services/remote_video.py).

export interface VideoItem {
  id: string; name: string; type: string; collection_type: string | null;
  is_folder: boolean; year: number | null; runtime_s: number;
  series_name: string | null; season: number | null; episode: number | null;
  overview: string | null; has_image: boolean; played: boolean;
  progress: number | null; resume_s: number;
}
export interface VideoPage { ok: boolean; items: VideoItem[]; total: number; start: number }
export interface VideoStream { index: number; label: string }
export interface VideoState {
  active: boolean; playing?: boolean; title?: string | null; item_id?: string | null;
  position_s?: number; duration_s?: number;
  audio_streams?: VideoStream[]; subtitle_streams?: VideoStream[];
  audio_index?: number | null; subtitle_index?: number | null;
}

export const PAGE_SIZE = 60;
export const TICKS_PER_SECOND = 10_000_000;
const PLAYABLE = new Set(["Movie", "Episode", "Video", "MusicVideo", "Trailer"]);

export function isPlayable(i: VideoItem): boolean {
  return PLAYABLE.has(i.type) && !i.is_folder;
}

/** Item types a library view lists at its top level. */
export function typesFor(collectionType: string | null | undefined): string {
  return collectionType === "movies" ? "Movie" : collectionType === "tvshows" ? "Series" : "";
}

export function imagePath(i: VideoItem, width = 320): string | null {
  return i.has_image ? `api/remote/video/image/${i.id}?max_width=${width}` : null;
}

export function itemsPath(o: { parentId?: string; types?: string; search?: string;
                               start?: number }): string {
  const q = new URLSearchParams();
  if (o.parentId) q.set("parent_id", o.parentId);
  if (o.types) q.set("type", o.types);
  if (o.search) q.set("search", o.search);
  q.set("start", String(o.start ?? 0));
  q.set("limit", String(PAGE_SIZE));
  return `api/remote/video/items?${q.toString()}`;
}

export function clock(sec: number | null | undefined): string {
  const s = Math.max(0, Math.floor(sec ?? 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

export function itemSubtitle(i: VideoItem): string {
  const parts: string[] = [];
  if (i.type === "Episode") {
    const se = i.season != null && i.episode != null ? `S${i.season}E${i.episode}` : "";
    parts.push([i.series_name, se].filter(Boolean).join(" · "));
  }
  if (i.year) parts.push(String(i.year));
  if (i.runtime_s) {
    const m = Math.round(i.runtime_s / 60);
    parts.push(m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`);
  }
  return parts.filter(Boolean).join(" · ");
}
