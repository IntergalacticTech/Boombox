import { useEffect, useState } from "react";
import { useApi, ApiError } from "../lib/api";

interface Playlist {
  name: string;
  uri: string;
}

interface PlaylistTrack {
  uri: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_s: number;
}

/** Playlist list + drill-into-detail. Tapping the row body drills in;
 *  the ▶ on each row queues + plays the whole playlist immediately.
 *  Creation lives on the Search tab ("Save as playlist"). */
export function Playlists() {
  const api = useApi();
  const [playlists, setPlaylists] = useState<Playlist[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [detail, setDetail] = useState<Playlist | null>(null);

  const reload = () => {
    setBusy(true);
    setErr(null);
    api
      .get<{ ok: boolean; playlists: Playlist[] }>("api/remote/playlists")
      .then((r) => setPlaylists(r.playlists))
      .catch((e: unknown) =>
        setErr(e instanceof ApiError ? `${e.status}` : "failed"))
      .finally(() => setBusy(false));
  };

  useEffect(reload, []); // eslint-disable-line react-hooks/exhaustive-deps

  const playList = async (p: Playlist) => {
    setToast(`Loading ${p.name}…`);
    try {
      const { uris } = await api.get<{ ok: boolean; uris: string[] }>(
        `api/remote/playlists/${encodeURIComponent(p.uri)}/items`,
      );
      if (uris.length === 0) {
        setToast(`${p.name} is empty.`);
        return;
      }
      await api.post("api/remote/queue", { uris, play: true });
      setToast(`Playing ${p.name} (${uris.length} track${uris.length === 1 ? "" : "s"}).`);
    } catch (e: unknown) {
      setToast(e instanceof ApiError ? `Failed (${e.status})` : "Failed");
    }
  };

  if (detail) {
    return <PlaylistDetail playlist={detail}
                            onBack={() => { setDetail(null); reload(); }} />;
  }

  return (
    <div style={{ padding: 16, paddingBottom: 96 }}>
      <header style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 20 }}>Playlists</h2>
        <button type="button" onClick={reload} style={smallBtn}
                aria-label="Refresh">↻</button>
      </header>

      {toast && (
        <div role="status" style={banner}>{toast}</div>
      )}
      {err && (
        <div role="alert" style={{ ...banner, color: "var(--accent2)" }}>
          Error: {err}
        </div>
      )}

      {busy && !playlists && (
        <div style={{ color: "var(--ink2)" }}>Loading…</div>
      )}
      {playlists && playlists.length === 0 && (
        <div style={{ color: "var(--ink2)", padding: "16px 4px" }}>
          No playlists yet. Use Search → "Save as playlist" to make one.
        </div>
      )}

      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {playlists?.map((p) => (
          <li key={p.uri} style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "10px 4px", borderBottom: "1px solid var(--rule)",
          }}>
            <button type="button"
                    onClick={() => setDetail(p)}
                    aria-label={`Open ${p.name || "playlist"}`}
                    style={{ ...rowBtn, flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 15, overflow: "hidden",
                            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {p.name || "Untitled"}
              </div>
              <div style={{ color: "var(--ink2)", fontSize: 12,
                            fontFamily: "var(--mono)",
                            overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap" }}>
                {p.uri}
              </div>
            </button>
            <button type="button" aria-label={`Play ${p.name || "playlist"}`}
                    onClick={() => playList(p)} style={smallBtn}>▶</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PlaylistDetail(
  { playlist, onBack }: { playlist: Playlist; onBack: () => void },
) {
  const api = useApi();
  const [tracks, setTracks] = useState<PlaylistTrack[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [name, setName] = useState(playlist.name);

  const reload = () => {
    setBusy(true);
    setErr(null);
    api
      .get<{ ok: boolean; tracks: PlaylistTrack[] }>(
        `api/remote/playlists/${encodeURIComponent(playlist.uri)}/items`,
      )
      .then((r) => setTracks(r.tracks))
      .catch((e: unknown) =>
        setErr(e instanceof ApiError ? `${e.status}` : "failed"))
      .finally(() => setBusy(false));
  };
  useEffect(reload, [playlist.uri]); // eslint-disable-line react-hooks/exhaustive-deps

  const rename = async () => {
    const next = window.prompt("Rename playlist", name);
    if (!next || !next.trim() || next.trim() === name) return;
    setToast("Renaming…");
    try {
      const r = await api.post<{ ok: boolean; name: string }>(
        `api/remote/playlists/${encodeURIComponent(playlist.uri)}/rename`,
        { name: next.trim() },
      );
      setName(r.name || next.trim());
      setToast(`Renamed to "${r.name || next.trim()}".`);
    } catch (e: unknown) {
      setToast(
        e instanceof ApiError ? `Rename failed (${e.status})` : "Rename failed",
      );
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete playlist "${name}"? This cannot be undone.`)) {
      return;
    }
    try {
      await api.post(
        `api/remote/playlists/${encodeURIComponent(playlist.uri)}/delete`,
      );
      onBack();
    } catch (e: unknown) {
      setToast(
        e instanceof ApiError ? `Delete failed (${e.status})` : "Delete failed",
      );
    }
  };

  const playOne = async (uri: string, label: string) => {
    setToast(null);
    try {
      await api.post("api/remote/queue", { uris: [uri], play: true });
      setToast(`Playing: ${label}`);
    } catch (e: unknown) {
      setToast(e instanceof ApiError ? `Failed (${e.status})` : "Failed");
    }
  };

  const playAll = async () => {
    if (!tracks || tracks.length === 0) return;
    setToast(null);
    try {
      await api.post("api/remote/queue",
                     { uris: tracks.map((t) => t.uri), play: true });
      setToast(`Playing ${tracks.length} track(s).`);
    } catch (e: unknown) {
      setToast(e instanceof ApiError ? `Failed (${e.status})` : "Failed");
    }
  };

  const removeOne = async (uri: string) => {
    setToast(null);
    try {
      await api.post(
        `api/remote/playlists/${encodeURIComponent(playlist.uri)}/remove_item`,
        { uri },
      );
      setToast("Removed.");
      reload();
    } catch (e: unknown) {
      setToast(e instanceof ApiError ? `Failed (${e.status})` : "Failed");
    }
  };

  const moveOne = async (from_index: number, to_index: number) => {
    // Optimistic: splice locally, then send. reload() reconciles.
    setTracks((prev) => {
      if (!prev) return prev;
      const next = prev.slice();
      const [moved] = next.splice(from_index, 1);
      const target = Math.max(0, Math.min(next.length, to_index));
      next.splice(target, 0, moved);
      return next;
    });
    try {
      await api.post(
        `api/remote/playlists/${encodeURIComponent(playlist.uri)}/move_item`,
        { from_index, to_index },
      );
      reload();
    } catch (e: unknown) {
      setToast(e instanceof ApiError ? `Failed (${e.status})` : "Failed");
      reload();
    }
  };

  return (
    <div style={{ padding: 16, paddingBottom: 96 }}>
      <header style={{ display: "flex", alignItems: "center", gap: 8,
                       marginBottom: 12, flexWrap: "wrap" }}>
        <button type="button" onClick={onBack} style={iconBtn}
                aria-label="Back">‹</button>
        <h2 style={{ margin: 0, fontSize: 20, flex: 1, minWidth: 0,
                     overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}>
          {name}
        </h2>
        <button type="button" onClick={rename} style={iconBtn}
                aria-label="Rename playlist">✎</button>
        <button type="button" onClick={remove} style={iconBtn}
                aria-label="Delete playlist">🗑</button>
        <button type="button" onClick={playAll}
                disabled={!tracks || tracks.length === 0}
                style={smallBtn}>▶ Play all</button>
      </header>

      {toast && <div role="status" style={banner}>{toast}</div>}
      {err && <div role="alert" style={{ ...banner, color: "var(--accent2)" }}>
        Error: {err}
      </div>}

      {busy && !tracks && <div style={{ color: "var(--ink2)" }}>Loading…</div>}
      {tracks && tracks.length === 0 && (
        <div style={{ color: "var(--ink2)", padding: "16px 4px" }}>
          Empty playlist.
        </div>
      )}

      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {tracks?.map((t, i) => (
          <li key={`${t.uri}#${i}`} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "10px 4px", borderBottom: "1px solid var(--rule)",
          }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 15, overflow: "hidden",
                            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {t.title ?? <em style={{ color: "var(--ink2)" }}>missing</em>}
              </div>
              <div style={{ color: "var(--ink2)", fontSize: 12,
                            overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap" }}>
                {[t.artist, t.album].filter(Boolean).join(" · ") || t.uri}
              </div>
            </div>
            <button type="button"
                    aria-label={`Move ${t.title ?? t.uri} up`}
                    disabled={i === 0}
                    onClick={() => moveOne(i, i - 1)}
                    style={miniIconBtn}>▲</button>
            <button type="button"
                    aria-label={`Move ${t.title ?? t.uri} down`}
                    disabled={i === (tracks?.length ?? 0) - 1}
                    onClick={() => moveOne(i, i + 1)}
                    style={miniIconBtn}>▼</button>
            <button type="button"
                    aria-label={`Play ${t.title ?? t.uri}`}
                    onClick={() => playOne(t.uri, t.title ?? t.uri)}
                    style={smallBtn}>▶</button>
            <button type="button"
                    aria-label={`Remove ${t.title ?? t.uri}`}
                    onClick={() => removeOne(t.uri)}
                    style={iconBtn}>×</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

const banner: React.CSSProperties = {
  padding: "8px 12px", marginBottom: 12, borderRadius: 8,
  background: "var(--panel)", color: "var(--ink2)", fontSize: 13,
};
const smallBtn: React.CSSProperties = {
  padding: "6px 10px", borderRadius: 6,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", fontSize: 13, cursor: "pointer",
};
const iconBtn: React.CSSProperties = {
  width: 32, height: 32, borderRadius: 16,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink2)", cursor: "pointer", fontSize: 16, lineHeight: 1,
};
const miniIconBtn: React.CSSProperties = {
  width: 28, height: 32, borderRadius: 6,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink2)", cursor: "pointer", fontSize: 10, lineHeight: 1,
  padding: 0,
};
const rowBtn: React.CSSProperties = {
  background: "transparent", border: 0, color: "var(--ink)",
  fontSize: 15, padding: "2px 4px", cursor: "pointer",
  textAlign: "left",
};
