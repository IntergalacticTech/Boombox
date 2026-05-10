// QueueDrawer — view + manipulate Mopidy's tracklist (the queue).
//
// We poll once on open and on each playback event via a 2s interval (cheap;
// the queue rarely changes mid-session). Tap a row → jump to that track.
// Tap × on a row → remove from queue (current track stays playing).

import { useEffect, useRef, useState } from "react";
import { getQueue, getCurrentTlid, playTlid, removeTlid, type TlTrack } from "./library";

function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function joinArtists(t: TlTrack): string {
  return (t.track.artists ?? []).map(a => a?.name).filter(Boolean).join(", ");
}

type Props = { onClose: () => void };

export function QueueDrawer({ onClose }: Props) {
  const [items, setItems] = useState<TlTrack[]>([]);
  const [currentTlid, setCurrentTlid] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const aborted = useRef(false);

  useEffect(() => {
    aborted.current = false;
    const refresh = async () => {
      try {
        const [q, cur] = await Promise.all([getQueue(), getCurrentTlid()]);
        if (aborted.current) return;
        setItems(q);
        setCurrentTlid(cur);
      } catch {
        // ignore — next tick will retry
      } finally {
        if (!aborted.current) setLoading(false);
      }
    };
    refresh();
    const id = setInterval(refresh, 2000);
    return () => { aborted.current = true; clearInterval(id); };
  }, []);

  // Esc closes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onJump = async (tlid: number) => {
    await playTlid(tlid);
    onClose();
  };

  const onRemove = async (tlid: number) => {
    setItems(prev => prev.filter(t => t.tlid !== tlid));
    try { await removeTlid(tlid); } catch { /* refresh will reconcile */ }
  };

  return (
    <div
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.92)",
        backdropFilter: "blur(20px)",
        zIndex: 9990,
        display: "flex",
        alignItems: "stretch",
        justifyContent: "center",
        padding: 16,
        fontFamily: "Inter, system-ui, sans-serif",
        color: "#fff",
      }}
    >
      <div style={{
        width: "min(1100px, 96vw)",
        maxHeight: "100%",
        background: "#0a0a0a",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 16,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}>
        <div style={{
          padding: "14px 18px",
          borderBottom: "1px solid rgba(255,255,255,0.10)",
          display: "flex",
          alignItems: "center",
          gap: 12,
          minHeight: 60,
        }}>
          <button
            onClick={onClose}
            style={{
              padding: "10px 14px",
              background: "rgba(255,255,255,0.08)",
              border: "1px solid rgba(255,255,255,0.15)",
              borderRadius: 999,
              color: "#fff", fontSize: 14, cursor: "pointer",
              minWidth: 64,
            }}
          >Close</button>
          <div style={{flex: 1, minWidth: 0}}>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11, letterSpacing: "0.18em",
              color: "rgba(255,255,255,0.55)",
            }}>QUEUE</div>
            <div style={{fontSize: 18, fontWeight: 700, marginTop: 2}}>
              {items.length} track{items.length === 1 ? "" : "s"}
            </div>
          </div>
        </div>

        <div style={{flex: 1, overflowY: "auto", overflowX: "hidden"}}>
          {loading && (
            <div style={{padding: 24, fontFamily: "'JetBrains Mono', monospace", color: "rgba(255,255,255,0.6)"}}>Loading…</div>
          )}
          {!loading && items.length === 0 && (
            <div style={{padding: 24, fontFamily: "'JetBrains Mono', monospace", color: "rgba(255,255,255,0.5)"}}>
              Queue is empty. Add tracks from the library.
            </div>
          )}
          {!loading && items.map((t) => {
            const playing = t.tlid === currentTlid;
            return (
              <div key={t.tlid} style={{
                display: "flex", alignItems: "center", gap: 0,
                background: playing ? "rgba(91,231,255,0.08)" : "transparent",
                borderBottom: "1px solid rgba(255,255,255,0.06)",
                borderLeft: playing ? "3px solid #5be7ff" : "3px solid transparent",
              }}>
                <button
                  onClick={() => onJump(t.tlid)}
                  style={{
                    flex: 1,
                    minWidth: 0,
                    textAlign: "left",
                    background: "transparent",
                    border: "none",
                    padding: "14px 18px",
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                    color: "inherit",
                    cursor: "pointer",
                    minHeight: 60,
                  }}
                >
                  <div style={{
                    width: 28, height: 28, borderRadius: 6,
                    background: playing ? "#5be7ff" : "rgba(255,255,255,0.06)",
                    color: playing ? "#000" : "rgba(255,255,255,0.7)",
                    display: "grid", placeItems: "center",
                    fontSize: 14, flexShrink: 0,
                  }}>{playing ? "♪" : "▶"}</div>
                  <div style={{flex: 1, minWidth: 0}}>
                    <div style={{
                      fontSize: 15, fontWeight: 600,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>{t.track.name || t.track.uri}</div>
                    <div style={{
                      fontSize: 12, color: "rgba(255,255,255,0.55)",
                      fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.04em",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      marginTop: 2,
                    }}>{joinArtists(t) || (t.track.album?.name ?? "")}</div>
                  </div>
                  <div style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12, color: "rgba(255,255,255,0.6)",
                    flexShrink: 0,
                  }}>{t.track.length ? formatDuration(t.track.length) : ""}</div>
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); onRemove(t.tlid); }}
                  aria-label="Remove from queue"
                  style={{
                    width: 56, height: 60,
                    flexShrink: 0,
                    background: "transparent",
                    border: "none",
                    color: "rgba(255,255,255,0.45)",
                    fontSize: 22,
                    cursor: "pointer",
                  }}
                >×</button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
