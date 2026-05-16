import { useEffect, useState } from "react";
import { useApi, ApiError } from "../lib/api";

interface Track {
  uri: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_s: number;
}

function mmss(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Library search. Hits the consolidated Mopidy search backend; results are
 *  capped server-side at 80 tracks. Each result is individually queue-able,
 *  plus a "Play all" that queues the whole result set + starts playback.
 *  Multi-select + "Save as playlist" lets the user build a playlist from
 *  the current result set in one tap. */
export function Search() {
  const api = useApi();
  const [q, setQ] = useState("");
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const term = q.trim();
    if (!term) return;
    setBusy(true);
    setErr(null);
    setSelected(new Set());
    api
      .get<{ ok: boolean; tracks: Track[] }>(
        `api/remote/library/search?q=${encodeURIComponent(term)}`,
      )
      .then((r) => setTracks(r.tracks))
      .catch((e: unknown) =>
        setErr(e instanceof ApiError ? `${e.status}` : "failed"))
      .finally(() => setBusy(false));
  };

  const toggleSelected = (uri: string) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(uri)) next.delete(uri); else next.add(uri);
      return next;
    });
  };

  const saveAsPlaylist = async (uris: string[]) => {
    const name = window.prompt(
      `Save ${uris.length} track${uris.length === 1 ? "" : "s"} as playlist — name?`,
    );
    if (!name || !name.trim()) return;
    setToast("Creating playlist…");
    try {
      await api.post<{ ok: boolean; uri: string }>(
        "api/remote/playlists",
        { name: name.trim(), uris },
      );
      setToast(`Saved playlist "${name.trim()}".`);
      setSelected(new Set());
    } catch (e: unknown) {
      setToast(
        e instanceof ApiError ? `Save failed (${e.status})` : "Save failed",
      );
    }
  };

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerUris, setPickerUris] = useState<string[]>([]);
  const openPicker = (uris: string[]) => {
    setPickerUris(uris);
    setPickerOpen(true);
  };
  const addToPlaylist = async (target: { name: string; uri: string }) => {
    setPickerOpen(false);
    setToast(`Adding to "${target.name}"…`);
    try {
      const res = await api.post<{ ok: boolean; added: number }>(
        `api/remote/playlists/${encodeURIComponent(target.uri)}/append`,
        { uris: pickerUris },
      );
      setToast(`Added ${res.added ?? pickerUris.length} to "${target.name}".`);
      setSelected(new Set());
    } catch (e: unknown) {
      setToast(
        e instanceof ApiError ? `Add failed (${e.status})` : "Add failed",
      );
    }
  };

  const queueOne = async (t: Track, play: boolean) => {
    setToast(null);
    try {
      await api.post("api/remote/queue", { uris: [t.uri], play });
      setToast(play ? `Playing: ${t.title ?? t.uri}` : `Queued: ${t.title ?? t.uri}`);
    } catch (e: unknown) {
      setToast(e instanceof ApiError ? `Queue failed (${e.status})` : "Queue failed");
    }
  };

  const playAll = async () => {
    if (!tracks || tracks.length === 0) return;
    setToast(null);
    try {
      await api.post("api/remote/queue",
                     { uris: tracks.map((t) => t.uri), play: true });
      setToast(`Playing ${tracks.length} track(s)`);
    } catch (e: unknown) {
      setToast(e instanceof ApiError ? `Queue failed (${e.status})` : "Queue failed");
    }
  };

  return (
    <div style={{ padding: 16, paddingBottom: 96 }}>
      <form onSubmit={submit} style={{ display: "flex", gap: 8,
                                       marginBottom: 12 }}>
        <input type="search" aria-label="Search query"
               value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Search artist, album, track…"
               style={searchInput} />
        <button type="submit" disabled={busy || !q.trim()}
                style={primaryBtn}>
          {busy ? "…" : "Go"}
        </button>
      </form>

      {tracks && tracks.length > 0 && (
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 8, gap: 8 }}>
          <span style={{ color: "var(--ink2)", fontSize: 13 }}>
            {tracks.length} result{tracks.length === 1 ? "" : "s"}
            {selected.size > 0 && (
              <span style={{ marginLeft: 8, color: "var(--accent)" }}>
                ({selected.size} selected)
              </span>
            )}
          </span>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                        justifyContent: "flex-end" }}>
            {selected.size > 0 && (
              <>
                <button type="button" style={smallBtn}
                        onClick={() => saveAsPlaylist(Array.from(selected))}>
                  ＋ Save as playlist
                </button>
                <button type="button" style={smallBtn}
                        onClick={() => openPicker(Array.from(selected))}>
                  → Add to…
                </button>
              </>
            )}
            <button type="button" style={smallBtn}
                    onClick={() => saveAsPlaylist(tracks.map((t) => t.uri))}>
              ＋ All as playlist
            </button>
            <button type="button" onClick={playAll} style={smallBtn}>
              ▶ Play all
            </button>
          </div>
        </div>
      )}

      {toast && (
        <div role="status" style={{
          padding: "8px 12px", marginBottom: 12, borderRadius: 8,
          background: "var(--panel)", color: "var(--ink2)", fontSize: 13,
        }}>{toast}</div>
      )}
      {err && (
        <div role="alert" style={{
          padding: "8px 12px", marginBottom: 12, borderRadius: 8,
          background: "var(--panel)", color: "var(--accent2)", fontSize: 13,
        }}>Error: {err}</div>
      )}

      {tracks && tracks.length === 0 && (
        <div style={{ color: "var(--ink2)", padding: "16px 4px" }}>
          No results.
        </div>
      )}

      {pickerOpen && (
        <PlaylistPicker
          count={pickerUris.length}
          api={api}
          onPick={addToPlaylist}
          onCancel={() => setPickerOpen(false)}
        />
      )}

      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {tracks?.map((t) => (
          <li key={t.uri} style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "10px 4px", borderBottom: "1px solid var(--rule)",
          }}>
            <input type="checkbox"
                   aria-label={`Select ${t.title ?? t.uri}`}
                   checked={selected.has(t.uri)}
                   onChange={() => toggleSelected(t.uri)}
                   style={{ width: 18, height: 18, accentColor: "var(--accent)" }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 15, overflow: "hidden",
                            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {t.title ?? "Untitled"}
              </div>
              <div style={{ color: "var(--ink2)", fontSize: 12,
                            overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap" }}>
                {[t.artist, t.album].filter(Boolean).join(" · ")
                  || t.uri}
              </div>
            </div>
            <span style={{ color: "var(--ink2)", fontSize: 12,
                           fontFamily: "var(--mono)" }}>
              {mmss(t.duration_s)}
            </span>
            <button type="button" aria-label={`Play ${t.title ?? t.uri}`}
                    onClick={() => queueOne(t, true)} style={smallBtn}>
              ▶
            </button>
            <button type="button" aria-label={`Queue ${t.title ?? t.uri}`}
                    onClick={() => queueOne(t, false)} style={smallBtn}>
              +
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PlaylistPicker(
  { count, api, onPick, onCancel }: {
    count: number;
    api: ReturnType<typeof useApi>;
    onPick: (p: { name: string; uri: string }) => void;
    onCancel: () => void;
  },
) {
  const [items, setItems] = useState<{ name: string; uri: string }[] | null>(null);
  useEffect(() => {
    api.get<{ ok: boolean; playlists: { name: string; uri: string }[] }>(
      "api/remote/playlists",
    ).then((r) => setItems(r.playlists))
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
            Add {count} track{count === 1 ? "" : "s"} to…
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
            No playlists yet. Use "Save as playlist" to create one.
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

const searchInput: React.CSSProperties = {
  flex: 1, padding: "10px 12px", borderRadius: 8,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", fontSize: 15,
};
const primaryBtn: React.CSSProperties = {
  padding: "10px 14px", borderRadius: 8, border: 0,
  background: "var(--accent)", color: "var(--bg)",
  fontSize: 14, fontWeight: 600, cursor: "pointer",
};
const smallBtn: React.CSSProperties = {
  padding: "6px 10px", borderRadius: 6,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", fontSize: 13, cursor: "pointer",
};
