// Track favorites — localStorage-backed set of "I liked this" track URIs.
//
// Lives entirely client-side; no Mopidy plugin required. Subscribers (the
// favorite button + the Favorites library view) react instantly to changes
// since toggling publishes to all hooks.
//
// Phase 2: when the toggled URI is a Home Library track (subsonic:track:<id>
// canonical form, or a file:// URI we can map back), we ALSO call the
// libraryApi pin/unpin endpoints with source='favorite' so the heart and
// the offline pin stay in sync.

import { useEffect, useState } from "react";
import * as libraryApi from "./libraryApi";

const KEY = "boombox.favorites";

let _set: Set<string> = readPersisted();
const _subs = new Set<(s: ReadonlySet<string>) => void>();

function readPersisted(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    if (Array.isArray(arr)) return new Set(arr.filter((x): x is string => typeof x === "string"));
    return new Set();
  } catch { return new Set(); }
}

function persist() {
  try { localStorage.setItem(KEY, JSON.stringify([..._set])); } catch { /* ignore */ }
}

function publish() {
  for (const s of _subs) s(_set);
}

/** Extract a Subsonic track id from a Mopidy / Home Library URI, or null. */
export function subsonicIdFromUri(uri: string | null | undefined): string | null {
  if (!uri) return null;
  if (uri.startsWith("subsonic:track:")) return uri.slice("subsonic:track:".length);
  // file:///cache-mount/audio/<id>.<suffix> — Phase 1 downloader names files
  // <track_id>.<suffix>, so basename-minus-suffix recovers the id.
  if (uri.startsWith("file://")) {
    const path = decodeURIComponent(uri.slice("file://".length));
    const base = path.split("/").pop() ?? "";
    const dot = base.lastIndexOf(".");
    if (dot > 0) return base.slice(0, dot);
  }
  return null;
}

export function isFavorite(uri: string | null | undefined): boolean {
  return !!uri && _set.has(uri);
}

export function toggleFavorite(uri: string | null | undefined): void {
  if (!uri) return;
  const next = new Set(_set);
  const becomingFavorite = !next.has(uri);
  if (becomingFavorite) next.add(uri); else next.delete(uri);
  _set = next;
  persist();
  publish();

  const subsonicId = subsonicIdFromUri(uri);
  if (subsonicId) {
    // Auto-pin/unpin with source='favorite'. Errors are swallowed — the heart
    // already toggled visually; the worst case is the offline pin drifts and
    // the next sync reconciles.
    if (becomingFavorite) {
      libraryApi.pin("track", subsonicId, "favorite").catch(() => { /* ignore */ });
    } else {
      libraryApi.unpin("track", subsonicId, "favorite").catch(() => { /* ignore */ });
    }
  }
}

export function getFavorites(): string[] {
  return [..._set];
}

/** React hook returning the set of favorite URIs. Re-renders on toggle. */
export function useFavorites(): ReadonlySet<string> {
  const [state, setState] = useState<ReadonlySet<string>>(_set);
  useEffect(() => {
    const sub = (s: ReadonlySet<string>) => setState(s);
    _subs.add(sub);
    return () => { _subs.delete(sub); };
  }, []);
  return state;
}
