import { useCallback, useEffect, useState } from "react";
import { useApi, ApiError } from "../lib/api";

interface QueueRow {
  tlid: number;
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

  const clearAll = async () => {
    if (!window.confirm("Clear the queue?")) return;
    try {
      await api.post("api/remote/queue/clear");
    } catch { /* surfaced on next refresh */ }
    load();
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
          <button type="button" onClick={clearAll} style={smallBtn}>
            Clear
          </button>
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
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {rows?.map((t) => (
          <li key={t.tlid} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "6px 4px", borderBottom: "1px solid var(--rule)",
            background: t.playing ? "var(--panel)" : "transparent",
            borderRadius: t.playing ? 6 : 0,
            opacity: busyTlid === t.tlid ? 0.5 : 1,
          }}>
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
