// Album-art lookup hook backed by /api/art (iTunes Search behind a cache).
//
// Browser-side dedupes pending requests: if two rows ask for the same
// (artist|album) at once, they share a single fetch. The server-side cache
// keeps ~zero bandwidth for repeat lookups across reloads.

import { useEffect, useRef, useState } from "react";

const _cache = new Map<string, string | null>();
const _pending = new Map<string, Promise<string | null>>();

function key(artist?: string | null, album?: string | null, track?: string | null): string {
  return `${(artist ?? "").trim().toLowerCase()}|${(album ?? "").trim().toLowerCase()}|${(track ?? "").trim().toLowerCase()}`;
}

async function fetchArt(artist?: string | null, album?: string | null, track?: string | null): Promise<string | null> {
  const k = key(artist, album, track);
  if (_cache.has(k)) return _cache.get(k) ?? null;
  if (_pending.has(k)) return _pending.get(k)!;
  const params = new URLSearchParams();
  if (artist) params.set("artist", artist);
  if (album)  params.set("album",  album);
  if (track && !album) params.set("track", track);
  const p = (async () => {
    try {
      const r = await fetch(`/api/art?${params.toString()}`, { cache: "force-cache" });
      if (!r.ok) return null;
      const j = await r.json();
      const url = (j?.url as string | null) ?? null;
      _cache.set(k, url);
      return url;
    } catch {
      _cache.set(k, null);
      return null;
    } finally {
      _pending.delete(k);
    }
  })();
  _pending.set(k, p);
  return p;
}

/** Returns the artwork URL for an artist+album (or artist+track), or null
 * while loading / not found. Stable identity: same key returns same URL on
 * subsequent renders without re-fetching. */
export function useAlbumArt(artist?: string | null, album?: string | null, track?: string | null): string | null {
  const k = key(artist, album, track);
  const [url, setUrl] = useState<string | null>(_cache.get(k) ?? null);
  const aborted = useRef(false);

  useEffect(() => {
    aborted.current = false;
    if (!artist && !album && !track) {
      setUrl(null);
      return;
    }
    const cached = _cache.get(k);
    if (cached !== undefined) {
      setUrl(cached);
      return;
    }
    fetchArt(artist, album, track).then((u) => {
      if (!aborted.current) setUrl(u);
    });
    return () => { aborted.current = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [k]);

  return url;
}
