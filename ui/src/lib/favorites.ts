// Track favorites — localStorage-backed set of "I liked this" track URIs.
//
// Lives entirely client-side; no Mopidy plugin required. Subscribers (the
// favorite button + the Favorites library view) react instantly to changes
// since toggling publishes to all hooks.

import { useEffect, useState } from "react";

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

export function isFavorite(uri: string | null | undefined): boolean {
  return !!uri && _set.has(uri);
}

export function toggleFavorite(uri: string | null | undefined): void {
  if (!uri) return;
  const next = new Set(_set);
  if (next.has(uri)) next.delete(uri);
  else next.add(uri);
  _set = next;
  persist();
  publish();
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
