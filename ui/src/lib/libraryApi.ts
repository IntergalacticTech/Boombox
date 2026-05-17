// libraryApi — typed client for the boombox-library service (port 6687,
// fronted by nginx at /api/library/*). Mirrors updaterApi.ts.
//
// Passwords flow PUT-only — GET /source never returns them.

export type SourceConfig = { url: string; username: string };
export type SourceConfigWithPassword = SourceConfig & { password: string };

export type Health = {
  service_version: string;
  navidrome_reachable: boolean;
  cache_present: boolean;
  cache_mount: string | null;
  last_sync_ts: number;       // 0 if never synced
  syncing: boolean;
};

export type BrowseType = "artists" | "albums" | "playlists";

export type BrowseItem = {
  id: string;
  name: string;
  artist_id?: string;
  year?: number;
  album_count?: number;
  song_count?: number;
  art_id?: string;
};

export type SearchResult = {
  content_type: "artist" | "album" | "track";
  id: string;
  title: string;
};

export type PinKind = "album" | "artist" | "playlist" | "track";
export type PinSource = "user" | "favorite";  // STARRED / RFID are backend-internal

export type CacheStats = {
  present: boolean;
  mount_path?: string | null;
  capacity: number;
  free: number;
  pinned_bytes: number;
  streamed_bytes: number;
  reserved: number;
};

export type CacheCandidate = {
  mount_path: string;
  label: string;
  free_bytes: number | null;
  total_bytes: number | null;
};

export type PlaybackResolution = {
  source: "cache" | "stream" | "offline_miss";
  uri: string | null;
  cache_status: "present" | "absent" | "queued" | "downloading" | "error";
};

async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = (await r.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error || `HTTP ${r.status}`);
  }
  return (await r.json()) as T;
}

export async function getHealth(): Promise<Health> {
  return jsonOrThrow(await fetch("/api/library/health"));
}

export async function getSource(): Promise<SourceConfig> {
  return jsonOrThrow(await fetch("/api/library/source"));
}

export async function putSource(s: SourceConfigWithPassword): Promise<{ ok: boolean }> {
  return jsonOrThrow(await fetch("/api/library/source", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  }));
}

export async function testSource(s: SourceConfigWithPassword): Promise<{ ok: boolean; error?: string }> {
  // /source/test always returns 200 (with ok:false on failure); don't throw.
  const r = await fetch("/api/library/source/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  });
  return r.json();
}

export async function browse(type: BrowseType): Promise<BrowseItem[]> {
  const r = await fetch(`/api/library/browse?type=${type}`);
  const body = await jsonOrThrow<{ items: BrowseItem[] }>(r);
  return body.items;
}

export async function search(q: string): Promise<SearchResult[]> {
  if (!q.trim()) return [];
  const r = await fetch(`/api/library/search?q=${encodeURIComponent(q)}`);
  const body = await jsonOrThrow<{ results: SearchResult[] }>(r);
  return body.results;
}

export async function pin(
  kind: PinKind, id: string, source: PinSource = "user",
): Promise<void> {
  await jsonOrThrow(await fetch("/api/library/pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, id, mode: "pin", source }),
  }));
}

export async function unpin(
  kind: PinKind, id: string, source?: PinSource,
): Promise<void> {
  const payload: Record<string, unknown> = { kind, id, mode: "unpin" };
  if (source) payload.source = source;
  await jsonOrThrow(await fetch("/api/library/pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }));
}

export async function runSync(): Promise<void> {
  await jsonOrThrow(await fetch("/api/library/sync/run", { method: "POST" }));
}

export async function getCacheStats(): Promise<CacheStats> {
  return jsonOrThrow(await fetch("/api/library/cache/stats"));
}

export async function adoptCache(mountPath: string): Promise<void> {
  await jsonOrThrow(await fetch("/api/library/cache/adopt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mount_path: mountPath }),
  }));
}

export async function clearStreamedCache(): Promise<{ cleared: number }> {
  return jsonOrThrow(await fetch("/api/library/cache/clear", { method: "POST" }));
}

export async function triggerStreamedCacheDownload(trackId: string): Promise<void> {
  await jsonOrThrow(await fetch(
    `/api/library/cache/streamed?id=${encodeURIComponent(trackId)}`,
    { method: "POST" },
  ));
}

export async function getCacheCandidates(): Promise<CacheCandidate[]> {
  const body = await jsonOrThrow<{ candidates: CacheCandidate[] }>(
    await fetch("/api/library/cache/candidates"),
  );
  return body.candidates;
}

export async function getResolver(trackId: string): Promise<PlaybackResolution> {
  return jsonOrThrow(await fetch(
    `/api/library/track/${encodeURIComponent(trackId)}/playback`,
  ));
}
