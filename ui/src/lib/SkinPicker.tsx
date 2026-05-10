// SkinPicker — full-screen overlay for choosing which skin renders the
// boombox. Triggered by the per-skin chrome (or the keyboard "s" shortcut
// in dev). Selecting a skin writes localStorage and reloads the page; per-
// skin layout state is decoupled from the React tree, so a fresh load is
// the simplest "switch" semantics.

import { useEffect } from "react";
import { SKINS, type SkinMeta } from "./skinRegistry";
import type { SkinId } from "./types";

type Props = {
  activeId: SkinId;
  onClose: () => void;
};

export function SkinPickerDrawer({ activeId, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const pick = (id: SkinId) => {
    if (id === activeId) { onClose(); return; }
    localStorage.setItem("boombox.skin", id);
    const url = new URL(window.location.href);
    url.searchParams.set("skin", id);
    window.location.replace(url.toString());
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
        padding: 12,
        fontFamily: "Inter, system-ui, sans-serif",
        color: "#fff",
      }}
    >
      <div style={{
        width: "min(1100px, 100%)",
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
          <div style={{flex: 1}}>
            <div style={{fontSize: 18, fontWeight: 700, letterSpacing: "-0.02em"}}>Skins</div>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10, letterSpacing: "0.18em",
              color: "rgba(255,255,255,0.5)", marginTop: 2,
            }}>ACTIVE · {activeId.toUpperCase()}</div>
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
          padding: 12,
        }}>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
            gap: 12,
          }}>
            {SKINS.map((s: SkinMeta) => {
              const active = s.id === activeId;
              return (
                <button
                  key={s.id}
                  onClick={() => pick(s.id)}
                  style={{
                    textAlign: "left",
                    padding: 14,
                    background: active ? "rgba(255,255,255,0.07)" : "rgba(255,255,255,0.02)",
                    border: `1.5px solid ${active ? "#fff" : "rgba(255,255,255,0.10)"}`,
                    borderRadius: 12,
                    color: "inherit",
                    cursor: "pointer",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                    minHeight: 130,
                  }}
                >
                  <div style={{display: "flex", alignItems: "center", justifyContent: "space-between"}}>
                    <span style={{fontSize: 17, fontWeight: 700, letterSpacing: "-0.01em"}}>{s.name}</span>
                    {active && (
                      <span style={{
                        fontSize: 10, fontFamily: "'JetBrains Mono', monospace",
                        letterSpacing: "0.18em", color: "#0a0a0a",
                        background: "#fff", padding: "3px 8px", borderRadius: 999,
                      }}>ACTIVE</span>
                    )}
                  </div>
                  <div style={{display: "flex", gap: 4, height: 24, borderRadius: 6, overflow: "hidden", border: "1px solid rgba(255,255,255,0.1)"}}>
                    {s.swatch.map((c, i) => (
                      <div key={i} style={{flex: 1, background: c}}/>
                    ))}
                  </div>
                  <div style={{
                    fontSize: 11,
                    color: "rgba(255,255,255,0.65)",
                    fontFamily: "'JetBrains Mono', monospace",
                    letterSpacing: "0.04em",
                    flex: 1,
                  }}>
                    {s.blurb}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
