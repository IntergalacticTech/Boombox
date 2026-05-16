import { useEffect, useState } from "react";
import { useApi } from "../lib/api";

interface Playlist { name: string; uri: string; }

/** Modal picker that lists every Mopidy playlist and resolves to a
 *  {name, uri} choice. Used from Search (multi-select selection),
 *  Library (album/artist/track row), Queue (single track), etc.
 *  Tap-outside dismisses. Pre-fetches the list on open. */
export function PlaylistPicker(
  { count, onPick, onCancel }: {
    count: number;
    onPick: (p: Playlist) => void;
    onCancel: () => void;
  },
) {
  const api = useApi();
  const [items, setItems] = useState<Playlist[] | null>(null);
  useEffect(() => {
    api.get<{ ok: boolean; playlists: Playlist[] }>("api/remote/playlists")
      .then((r) => setItems(r.playlists))
      .catch(() => setItems([]));
  }, [api]);

  return (
    <div role="dialog" aria-label="Add to playlist"
         onClick={onCancel}
         style={{
           position: "fixed", inset: 0, zIndex: 100,
           background: "rgba(0,0,0,0.5)",
           display: "flex", alignItems: "center", justifyContent: "center",
           padding: 16,
         }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        maxWidth: 360, width: "100%", maxHeight: "80vh", overflowY: "auto",
        background: "var(--panel)", borderRadius: 12,
        border: "1px solid var(--rule)", padding: 16,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "baseline", marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>
            {count < 0
              ? "Add to playlist…"
              : `Add ${count} track${count === 1 ? "" : "s"} to…`}
          </h3>
          <button type="button" onClick={onCancel}
                  aria-label="Cancel"
                  style={{ background: "transparent", border: 0,
                           color: "var(--ink2)", fontSize: 18,
                           cursor: "pointer" }}>×</button>
        </div>
        {!items && <div style={{ color: "var(--ink2)" }}>Loading…</div>}
        {items && items.length === 0 && (
          <div style={{ color: "var(--ink2)" }}>
            No playlists yet. Use Search → "Save as playlist" to create one.
          </div>
        )}
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {items?.map((p) => (
            <li key={p.uri}>
              <button type="button"
                      onClick={() => onPick(p)}
                      style={{
                        display: "block", width: "100%", textAlign: "left",
                        padding: "10px 4px", fontSize: 15,
                        background: "transparent",
                        border: 0, borderBottom: "1px solid var(--rule)",
                        color: "var(--ink)", cursor: "pointer",
                      }}>
                {p.name || p.uri}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
