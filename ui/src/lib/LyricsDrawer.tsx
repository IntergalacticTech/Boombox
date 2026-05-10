// LyricsDrawer — full-screen lyrics view, fetched from Lyrics.ovh via the
// /api/lyrics proxy. Falls back gracefully when no match exists.
//
// We re-fetch when artist/title changes, so the lyrics drawer stays in sync
// with the current track if the user leaves it open across track skips.

import { useEffect, useState } from "react";

type Props = {
  artist: string | null | undefined;
  title: string | null | undefined;
  onClose: () => void;
};

export function LyricsDrawer({ artist, title, onClose }: Props) {
  const [text, setText] = useState<string | null | undefined>(undefined); // undefined = loading
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!artist || !title) { setText(null); return; }
    let cancelled = false;
    setText(undefined);
    setErr(null);
    const params = new URLSearchParams({ artist, title });
    fetch(`/api/lyrics?${params.toString()}`)
      .then(r => r.ok ? r.json() : null)
      .then(j => {
        if (cancelled) return;
        setText((j?.lyrics as string | null) ?? null);
      })
      .catch(e => {
        if (!cancelled) { setText(null); setErr(String(e)); }
      });
    return () => { cancelled = true; };
  }, [artist, title]);

  return (
    <div
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.94)",
        backdropFilter: "blur(20px)",
        zIndex: 9990,
        display: "flex",
        alignItems: "stretch",
        justifyContent: "center",
        padding: 12,
        fontFamily: "Inter, system-ui, sans-serif",
        color: "#fff",
      }}
    >
      <div style={{
        width: "min(820px, 100%)",
        maxHeight: "100%",
        background: "#0a0a0a",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 16,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}>
        <div style={{
          padding: "12px 16px",
          borderBottom: "1px solid rgba(255,255,255,0.10)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexShrink: 0,
        }}>
          <div style={{flex: 1, minWidth: 0}}>
            <div style={{fontSize: 18, fontWeight: 700, letterSpacing: "-0.02em",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>{title || "Lyrics"}</div>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11, letterSpacing: "0.18em",
              color: "rgba(255,255,255,0.55)", marginTop: 2,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>{artist?.toUpperCase() || "—"} · LYRICS</div>
          </div>
          <button onClick={onClose} style={{
            padding: "10px 16px",
            background: "rgba(255,255,255,0.08)",
            color: "#fff",
            border: "1px solid rgba(255,255,255,0.15)",
            borderRadius: 999,
            fontSize: 14, cursor: "pointer",
            minWidth: 64,
          }}>Close</button>
        </div>

        <div style={{
          flex: 1,
          overflowY: "auto",
          overflowX: "hidden",
          overscrollBehavior: "contain",
          touchAction: "pan-y",
          WebkitOverflowScrolling: "touch",
          padding: "20px 24px 32px",
        }}>
          {text === undefined && (
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              color: "rgba(255,255,255,0.55)",
              padding: "40px 0",
            }}>fetching lyrics…</div>
          )}
          {text === null && (
            <div style={{padding: "40px 0", color: "rgba(255,255,255,0.6)"}}>
              <div style={{fontSize: 16, marginBottom: 6}}>No lyrics found.</div>
              <div style={{fontSize: 12, fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.06em"}}>
                Lyrics.ovh has nothing for “{artist} — {title}”.{err ? ` (${err})` : ""}
              </div>
            </div>
          )}
          {typeof text === "string" && text.length > 0 && (
            <div style={{
              fontSize: 16, lineHeight: 1.55,
              color: "rgba(255,255,255,0.92)",
              whiteSpace: "pre-wrap",
              fontFamily: "'JetBrains Mono', monospace",
              letterSpacing: "0.01em",
            }}>{text}</div>
          )}
        </div>
      </div>
    </div>
  );
}
