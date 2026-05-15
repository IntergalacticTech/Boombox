import { useState } from "react";
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
 *  plus a "Play all" that queues the whole result set + starts playback. */
export function Search() {
  const api = useApi();
  const [q, setQ] = useState("");
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const term = q.trim();
    if (!term) return;
    setBusy(true);
    setErr(null);
    api
      .get<{ ok: boolean; tracks: Track[] }>(
        `api/remote/library/search?q=${encodeURIComponent(term)}`,
      )
      .then((r) => setTracks(r.tracks))
      .catch((e: unknown) =>
        setErr(e instanceof ApiError ? `${e.status}` : "failed"))
      .finally(() => setBusy(false));
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
                      alignItems: "center", marginBottom: 8 }}>
          <span style={{ color: "var(--ink2)", fontSize: 13 }}>
            {tracks.length} result{tracks.length === 1 ? "" : "s"}
          </span>
          <button type="button" onClick={playAll} style={smallBtn}>
            ▶ Play all
          </button>
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

      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {tracks?.map((t) => (
          <li key={t.uri} style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "10px 4px", borderBottom: "1px solid var(--rule)",
          }}>
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
