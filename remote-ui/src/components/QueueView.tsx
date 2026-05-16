import { useCallback, useEffect, useState } from "react";
import { useApi, ApiError } from "../lib/api";
import { useDragSort } from "../lib/dragSort";

interface QueueRow {
  tlid: number;
  index: number;
  uri: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_s: number;
  playing: boolean;
}

/** Live tracklist viewer. Refreshes on the `refreshKey` prop (Now Playing
 *  bumps it on any state push so jumps/skips show up promptly) and on
 *  user actions. tlid is Mopidy's stable per-track handle; we use it for
 *  jump/remove since array indices shift under us when other clients
 *  edit the queue. */
export function QueueView({ refreshKey }: { refreshKey: number }) {
  const api = useApi();
  const [rows, setRows] = useState<QueueRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busyTlid, setBusyTlid] = useState<number | null>(null);

  const load = useCallback(() => {
    api
      .get<{ ok: boolean; tracks: QueueRow[] }>("api/remote/queue")
      .then((r) => setRows(r.tracks))
      .catch((e: unknown) =>
        setErr(e instanceof ApiError ? `${e.status}` : "failed"));
  }, [api]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const jump = async (tlid: number) => {
    setBusyTlid(tlid);
    try {
      await api.post("api/remote/queue/jump", { tlid });
    } catch { /* surfaced on next refresh */ }
    setBusyTlid(null);
    load();
  };

  const remove = async (tlid: number) => {
    setBusyTlid(tlid);
    try {
      await api.post("api/remote/queue/remove", { tlid });
    } catch { /* surfaced on next refresh */ }
    setBusyTlid(null);
    load();
  };

  const move = async (tlid: number, to_position: number) => {
    setBusyTlid(tlid);
    // Optimistically reorder so the row jumps before the server-round-trip
    // refresh — feels much more direct on a phone.
    setRows((prev) => {
      if (!prev) return prev;
      const i = prev.findIndex((r) => r.tlid === tlid);
      if (i < 0) return prev;
      const next = prev.slice();
      const [moved] = next.splice(i, 1);
      const target = Math.max(0, Math.min(next.length, to_position));
      next.splice(target, 0, moved);
      return next.map((r, ix) => ({ ...r, index: ix }));
    });
    try {
      await api.post("api/remote/queue/move", { tlid, to_position });
    } catch { /* surfaced on next refresh */ }
    setBusyTlid(null);
    load();
  };

  const clearAll = async () => {
    if (!window.confirm("Clear the queue?")) return;
    try {
      await api.post("api/remote/queue/clear");
    } catch { /* surfaced on next refresh */ }
    load();
  };

  const moveByIndex = (from: number, to: number) => {
    const r = rows?.[from];
    if (!r) return;
    void move(r.tlid, to);
  };
  const drag = useDragSort(rows?.length ?? 0, moveByIndex);

  const saveAsPlaylist = async () => {
    if (!rows || rows.length === 0) return;
    const name = window.prompt(
      `Save ${rows.length} queued track${rows.length === 1 ? "" : "s"} as playlist — name?`,
    );
    if (!name || !name.trim()) return;
    try {
      await api.post("api/remote/playlists",
                     { name: name.trim(), uris: rows.map((r) => r.uri) });
    } catch { /* best-effort; user will see the playlist (or not) */ }
  };

  return (
    <section aria-label="Queue" style={{ width: "100%" }}>
      <header style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "baseline", marginBottom: 6,
      }}>
        <h3 style={{ margin: 0, fontSize: 13, color: "var(--ink2)",
                     letterSpacing: "0.06em",
                     textTransform: "uppercase" }}>
          Queue {rows && `(${rows.length})`}
        </h3>
        {rows && rows.length > 0 && (
          <div style={{ display: "flex", gap: 6 }}>
            <button type="button" onClick={saveAsPlaylist}
                    style={smallBtn}>
              ＋ Save
            </button>
            <button type="button" onClick={clearAll} style={smallBtn}>
              Clear
            </button>
          </div>
        )}
      </header>
      {err && (
        <div role="alert" style={{
          padding: "6px 10px", marginBottom: 6, borderRadius: 6,
          background: "var(--panel)", color: "var(--accent2)", fontSize: 12,
        }}>Queue: {err}</div>
      )}
      {rows && rows.length === 0 && (
        <div style={{ color: "var(--ink2)", fontSize: 13,
                       padding: "8px 4px" }}>
          Nothing queued.
        </div>
      )}
      <ul style={{ listStyle: "none", padding: 0, margin: 0,
                    position: "relative" }}>
        {rows?.map((t, i) => (
          <li key={t.tlid} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "6px 4px", borderBottom: "1px solid var(--rule)",
            background: t.playing ? "var(--panel)" : "transparent",
            borderRadius: t.playing ? 6 : 0,
            opacity: busyTlid === t.tlid ? 0.5 : 1,
            ...drag.rowStyle(i),
          }}>
            <span {...drag.handleProps(i)}
                  role="button"
                  aria-label={`Drag ${t.title ?? t.uri} to reorder`}
                  style={{ ...drag.handleProps(i).style,
                           width: 16, color: "var(--ink2)",
                           fontSize: 14, textAlign: "center",
                           userSelect: "none" }}>≡</span>
            <span style={{ width: 12, color: "var(--accent)",
                           fontSize: 12, textAlign: "center" }}>
              {t.playing ? "▶" : ""}
            </span>
            <button type="button"
                    aria-label={`Jump to ${t.title ?? t.uri}`}
                    onClick={() => jump(t.tlid)} style={{
                      ...rowBtn, flex: 1, minWidth: 0,
                    }}>
              <div style={{ overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap", fontSize: 14 }}>
                {t.title ?? "Untitled"}
              </div>
              <div style={{ overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap", fontSize: 11,
                            color: "var(--ink2)" }}>
                {[t.artist, t.album].filter(Boolean).join(" · ") || t.uri}
              </div>
            </button>
            <button type="button"
                    aria-label={`Move ${t.title ?? t.uri} up`}
                    disabled={i === 0}
                    onClick={() => move(t.tlid, i - 1)}
                    style={miniIconBtn}>▲</button>
            <button type="button"
                    aria-label={`Move ${t.title ?? t.uri} down`}
                    disabled={i === (rows?.length ?? 0) - 1}
                    onClick={() => move(t.tlid, i + 1)}
                    style={miniIconBtn}>▼</button>
            <button type="button"
                    aria-label={`Remove ${t.title ?? t.uri}`}
                    onClick={() => remove(t.tlid)} style={iconBtn}>×</button>
          </li>
        ))}
      </ul>
    </section>
  );
}

const smallBtn: React.CSSProperties = {
  padding: "4px 8px", borderRadius: 6,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink2)", fontSize: 11, cursor: "pointer",
};
const miniIconBtn: React.CSSProperties = {
  width: 28, height: 36, borderRadius: 6,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink2)", cursor: "pointer", fontSize: 10, lineHeight: 1,
  padding: 0,
};
const iconBtn: React.CSSProperties = {
  // 36px target — small in a queue row so we don't dominate the title,
  // but still big enough for thumb taps on a phone.
  width: 36, height: 36, borderRadius: 18,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink2)", cursor: "pointer", fontSize: 16, lineHeight: 1,
};
const rowBtn: React.CSSProperties = {
  background: "transparent", border: 0, color: "var(--ink)",
  padding: "2px 4px", cursor: "pointer", textAlign: "left",
};
