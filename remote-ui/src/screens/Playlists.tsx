import { useEffect, useState } from "react";
import { useApi, ApiError } from "../lib/api";

interface Playlist {
  name: string;
  uri: string;
}

/** Playlist list + open-to-play. Each row shows the playlist name and a
 *  ▶ button that resolves its tracks via /playlists/{uri}/items and queues
 *  them. Creating a playlist from search results lives on the Search tab
 *  (sibling deploy) — this screen is intentionally focused on consumption. */
export function Playlists() {
  const api = useApi();
  const [playlists, setPlaylists] = useState<Playlist[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

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

  return (
    <div style={{ padding: 16, paddingBottom: 96 }}>
      <header style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 20 }}>Playlists</h2>
        <button type="button" onClick={reload} style={smallBtn}
                aria-label="Refresh">↻</button>
      </header>

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
            <div style={{ flex: 1, minWidth: 0 }}>
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
            </div>
            <button type="button" aria-label={`Play ${p.name || "playlist"}`}
                    onClick={() => playList(p)} style={smallBtn}>▶</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

const smallBtn: React.CSSProperties = {
  padding: "6px 10px", borderRadius: 6,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", fontSize: 13, cursor: "pointer",
};
