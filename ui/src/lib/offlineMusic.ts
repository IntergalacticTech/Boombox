// offlineMusic — what the kiosk can play while the homelab is unreachable.
//
// While useHomeLibraryOffline() is true, Home Library music that isn't on
// the boombox is dimmed, tagged "not offline" and can't be played (the LAN
// app's HomeLibrary screen does the same). Albums / artists / playlists
// count as kept when GET /api/library/offline lists them (≥ 1 track on
// disk); tracks carry their own `offline` flag on the Ref.

import { useEffect, useState } from "react";
import { getOfflineIds } from "./libraryApi";
import { parseHomeUri, type Ref } from "./library";

export const NOTHING_KEPT = "None of these tracks are on the boombox.";

/** Toast for a play that skipped `n` un-kept tracks. */
export function skippedMessage(n: number): string {
  return n === 1
    ? "1 track isn't on the boombox — playing the rest."
    : `${n} tracks aren't on the boombox — playing the rest.`;
}

export type OfflineSets = {
  album: Set<string>;
  artist: Set<string>;
  playlist: Set<string>;
};

/** The kept album / artist / playlist ids, fetched once each time `offline`
 * turns true (including on mount while offline). Null while online, while
 * loading, or when the fetch failed — callers then dim no containers. */
export function useOfflineSets(offline: boolean): OfflineSets | null {
  const [sets, setSets] = useState<OfflineSets | null>(null);
  useEffect(() => {
    if (!offline) { setSets(null); return; }
    let live = true;
    getOfflineIds()
      .then(r => {
        if (live) {
          setSets({
            album: new Set(r.album_ids ?? []),
            artist: new Set(r.artist_ids ?? []),
            playlist: new Set(r.playlist_ids ?? []),
          });
        }
      })
      .catch(() => { if (live) setSets(null); });
    return () => { live = false; };
  }, [offline]);
  return sets;
}

/** True when `ref` is Home Library music that can't play right now. Always
 * false while online; non-home refs (local, radio, folders) never count. */
export function isUnkept(ref: Pick<Ref, "uri" | "offline">, offline: boolean, sets: OfflineSets | null): boolean {
  if (!offline) return false;
  const p = parseHomeUri(ref.uri);
  if (!p) return false;
  if (p.kind === "track") return ref.offline === false;
  if (!sets) return false;
  const set = p.kind === "album" ? sets.album
    : p.kind === "artist" ? sets.artist
    : p.kind === "playlist" ? sets.playlist
    : null;
  return set !== null && !set.has(p.id);
}
