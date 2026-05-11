// SourceDrawer — full-screen overlay surfacing the four parallel input
// sources (Mopidy library, AirPlay, Spotify Connect, Bluetooth A2DP).
//
// All four are passive parallel receivers running side-by-side on PipeWire;
// the boombox-state aggregator surfaces whichever non-Mopidy MPRIS player
// is "active". This drawer gives the user agency on each source: browse
// the library, learn how to send AirPlay / Spotify, or trigger Bluetooth
// pairing mode. It also exposes a global "Stop external" when an external
// receiver has taken over.
//
// Triggered by the per-skin chrome bar — no longer a floating pill.

import { useEffect, useState } from "react";
import type { ActiveSource } from "./activeSource";
import { controlExternal } from "./activeSource";

type SourceId = "mopidy" | "movies" | "airplay" | "spotify" | "bluetooth" | "aux";

type SourceCard = {
  id: SourceId;
  name: string;
  tag: string;
  blurb: string;
  accent: string;
  glyph: string;
};

const CARDS: SourceCard[] = [
  {
    id: "mopidy",
    name: "Library",
    tag: "BUILT-IN",
    blurb: "Local music, playlists, internet radio",
    accent: "#5be7ff",
    glyph: "♪",
  },
  {
    id: "movies",
    name: "Movies",
    tag: "JELLYFIN",
    blurb: "Open Jellyfin on the touchscreen. A return pill appears top-left so you can come back here. Music pauses while video plays.",
    accent: "#ff7a35",
    glyph: "▶",
  },
  {
    id: "airplay",
    name: "AirPlay",
    tag: "iOS / macOS",
    blurb: "Pick “Boombox” from the AirPlay menu on your iPhone, iPad, or Mac",
    accent: "#a78bfa",
    glyph: "",
  },
  {
    id: "spotify",
    name: "Spotify",
    tag: "Connect",
    blurb: "Pick “Boombox” under Devices in any Spotify app",
    accent: "#1ed760",
    glyph: "♫",
  },
  {
    id: "bluetooth",
    name: "Bluetooth",
    tag: "A2DP",
    blurb: "Pair any phone or laptop to “Boombox” via Bluetooth",
    accent: "#5b9aff",
    glyph: "✦",
  },
  {
    // AUX is a physical-only source — there's no Pi-side detection or
    // auto-switch. The user flips it on at the amplifier; we just surface it
    // here so the source picker is honest about what's wired up.
    id: "aux",
    name: "AUX",
    tag: "Line-in",
    blurb: "Plug a 3.5 mm cable into the amplifier’s AUX jack and switch the amp to AUX",
    accent: "#f5a524",
    glyph: "◎",
  },
];

function activeIdFor(extSource: string | null, extStatus: string, mopidyPlaying: boolean): SourceId | null {
  const live = extStatus === "playing" || extStatus === "paused";
  if (live && extSource) {
    const s = extSource.toLowerCase();
    if (s.includes("shairport") || s.includes("airplay")) return "airplay";
    if (s.includes("spotify") || s.includes("librespot") || s.includes("raspotify")) return "spotify";
    if (s.includes("bluez") || s.includes("blue")) return "bluetooth";
  }
  return mopidyPlaying ? "mopidy" : null;
}

type ActionKind = "browse" | "info" | "pair" | "watch";

type Props = {
  ext: ActiveSource;
  mopidyPlaying: boolean;
  onClose: () => void;
  onOpenLibrary: () => void;
};

export function SourceDrawer({ ext, mopidyPlaying, onClose, onOpenLibrary }: Props) {
  const [expanded, setExpanded] = useState<SourceId | null>(null);
  const [pairStatus, setPairStatus] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);

  const active = activeIdFor(ext.source, ext.status, mopidyPlaying);
  const externalActive = active && active !== "mopidy";

  // Esc closes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const startBluetoothPairing = async () => {
    setPairStatus("starting…");
    try {
      const r = await fetch("/api/bluetooth/pair", { method: "POST" });
      if (!r.ok) throw new Error("pair failed");
      const j = await r.json();
      setPairStatus(j.message ?? "discoverable for 60 s — pair from your phone now");
    } catch {
      setPairStatus("could not start pairing — bluetoothctl unavailable?");
    }
  };

  const triggerCard = (id: SourceId) => {
    if (id === "mopidy") { onOpenLibrary(); return; }
    if (id === "movies") {
      // Best-effort pause Mopidy so a movie's audio doesn't fight music,
      // then swap the kiosk to Jellyfin. The kiosk extension's return
      // pill brings the user back.
      fetch("/mopidy/rpc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "core.playback.pause" }),
      }).catch(() => { /* fine */ });
      window.location.href = "http://localhost:8096/";
      return;
    }
    if (id === "bluetooth") {
      if (expanded === id) { setExpanded(null); return; }
      setExpanded(id);
      startBluetoothPairing();
      return;
    }
    setExpanded(expanded === id ? null : id);
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
        width: "min(960px, 100%)",
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
            <div style={{fontSize: 18, fontWeight: 700, letterSpacing: "-0.02em"}}>Sources</div>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10, letterSpacing: "0.18em",
              color: "rgba(255,255,255,0.5)", marginTop: 2,
            }}>
              {active ? `${active.toUpperCase()} · ${(ext.status ?? "READY").toUpperCase()}` : "NO SOURCE PLAYING"}
            </div>
          </div>
          {externalActive && (
            <button
              onClick={async () => {
                setStopping(true);
                try { await controlExternal("stop"); } finally { setStopping(false); }
              }}
              style={{
                padding: "10px 14px",
                background: "rgba(255,255,255,0.08)",
                color: "#fff",
                border: "1px solid rgba(255,255,255,0.20)",
                borderRadius: 999,
                fontSize: 12,
                fontFamily: "'JetBrains Mono', monospace",
                letterSpacing: "0.10em",
                cursor: "pointer",
              }}
            >{stopping ? "…" : "STOP"}</button>
          )}
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
        }}>
          {CARDS.map((c) => {
            const isActive = active === c.id;
            const isExpanded = expanded === c.id;
            const action = primaryActionFor(c.id);
            return (
              <div key={c.id} style={{
                borderBottom: "1px solid rgba(255,255,255,0.06)",
                background: isActive ? "rgba(255,255,255,0.04)" : "transparent",
                borderLeft: `4px solid ${isActive ? c.accent : "transparent"}`,
              }}>
                <button
                  onClick={() => triggerCard(c.id)}
                  style={{
                    width: "100%",
                    minHeight: 76,
                    padding: "12px 16px",
                    background: "transparent",
                    border: "none",
                    color: "inherit",
                    cursor: "pointer",
                    textAlign: "left",
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                  }}
                >
                  <span style={{
                    width: 44, height: 44, borderRadius: 10,
                    background: isActive ? c.accent : "rgba(255,255,255,0.08)",
                    color: isActive ? "#000" : "#fff",
                    display: "grid", placeItems: "center",
                    fontSize: 22, fontWeight: 700,
                    flexShrink: 0,
                  }}>{c.glyph || c.name[0]}</span>
                  <div style={{flex: 1, minWidth: 0}}>
                    <div style={{display: "flex", alignItems: "center", gap: 10}}>
                      <span style={{fontSize: 17, fontWeight: 700, letterSpacing: "-0.01em"}}>{c.name}</span>
                      {isActive && (
                        <span style={{
                          fontSize: 9, fontFamily: "'JetBrains Mono', monospace",
                          letterSpacing: "0.16em", color: "#0a0a0a",
                          background: c.accent, padding: "2px 6px", borderRadius: 999,
                        }}>{ext.status === "paused" ? "PAUSED" : "LIVE"}</span>
                      )}
                    </div>
                    <div style={{
                      fontSize: 11,
                      fontFamily: "'JetBrains Mono', monospace",
                      letterSpacing: "0.14em",
                      color: "rgba(255,255,255,0.5)",
                      marginTop: 2,
                    }}>{c.tag}</div>
                  </div>
                  <span style={{
                    padding: "8px 14px",
                    background: actionBgFor(action, c.accent),
                    color: action === "browse" || action === "pair" ? "#000" : "#fff",
                    border: action === "info" ? "1px solid rgba(255,255,255,0.20)" : "none",
                    borderRadius: 999,
                    fontWeight: 700,
                    fontSize: 12,
                    letterSpacing: "0.06em",
                    flexShrink: 0,
                  }}>{labelForAction(action, isExpanded)}</span>
                </button>
                {isExpanded && (
                  <div style={{
                    padding: "0 16px 14px 74px",
                    fontSize: 12,
                    color: "rgba(255,255,255,0.78)",
                    lineHeight: 1.45,
                  }}>
                    {c.blurb}
                    {c.id === "bluetooth" && pairStatus && (
                      <div style={{
                        marginTop: 8,
                        padding: "8px 12px",
                        background: "rgba(91,154,255,0.12)",
                        border: "1px solid rgba(91,154,255,0.28)",
                        borderRadius: 8,
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: 11, letterSpacing: "0.06em",
                        color: "#bfd0ff",
                      }}>{pairStatus}</div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function primaryActionFor(id: SourceId): ActionKind {
  if (id === "mopidy") return "browse";
  if (id === "movies") return "watch";
  if (id === "bluetooth") return "pair";
  return "info";
}

function actionBgFor(a: ActionKind, accent: string): string {
  if (a === "browse" || a === "pair" || a === "watch") return accent;
  return "transparent";
}

function labelForAction(a: ActionKind, expanded: boolean): string {
  if (a === "browse") return "▶ BROWSE";
  if (a === "watch")  return "▶ WATCH";
  if (a === "pair")   return expanded ? "DISCOVERABLE" : "PAIR DEVICE";
  return expanded ? "HIDE" : "HOW TO";
}
