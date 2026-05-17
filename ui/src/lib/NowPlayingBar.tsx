// NowPlayingBar — floating bottom strip with artwork, title, transport, and a
// system-wide volume slider. Rendered above any open drawer so the user never
// loses context while browsing library / queue / settings.
//
// Reads its data from the same hooks the skins use; keeps the kiosk always
// reactive to live state.

import { useEffect, useRef, useState } from "react";
import { useMopidy, useElapsed } from "./mopidy";
import { useActiveSource, isExternalActive, controlExternal } from "./activeSource";
import { AlbumThumb } from "./AlbumThumb";
import { LyricsDrawer } from "./LyricsDrawer";
import { toggleFavorite, useFavorites } from "./favorites";

type Props = { onDismiss?: () => void };

export function NowPlayingBar({ onDismiss }: Props = {}) {
  const m = useMopidy();
  const ext = useActiveSource(2000);
  const elapsed = useElapsed(m.state, m.positionMs, m.positionAtMs);
  const vol = useSystemVolume();
  const favs = useFavorites();
  const [lyricsOpen, setLyricsOpen] = useState(false);

  const externalActive = isExternalActive(ext);
  const title = externalActive ? (ext.track?.title ?? ext.label ?? ext.source ?? "External") : m.track?.title;
  const artist = externalActive ? (ext.track?.artist ?? "") : (m.track?.artist ?? "");
  const album = externalActive ? (ext.track?.album ?? "") : (m.track?.album ?? "");
  const state = externalActive ? ext.status : m.state;
  const len = externalActive ? Math.max(0, Math.floor(ext.length_ms / 1000)) : (m.track?.len ?? 0);
  const pos = externalActive ? Math.max(0, ext.position_ms / 1000) : elapsed;
  const playing = state === "playing";
  const pct = len > 0 ? Math.min(1, pos / len) : 0;

  const onToggle = externalActive ? () => controlExternal("toggle") : m.toggle;
  const onNext   = externalActive ? () => controlExternal("next")   : m.next;
  const onPrev   = externalActive ? () => controlExternal("previous"): m.prev;

  // If nothing is loaded at all, render nothing.
  if (!title) return null;

  return (
    <>
    <div style={{
      position: "fixed",
      bottom: 12,
      left: "50%",
      transform: "translateX(-50%)",
      width: "min(740px, calc(100vw - 24px))",
      zIndex: 9995,                     // above drawer overlays (9990)
      background: "rgba(15,17,24,0.92)",
      backdropFilter: "blur(20px)",
      border: "1px solid rgba(255,255,255,0.18)",
      borderRadius: 14,
      boxShadow: "0 18px 48px rgba(0,0,0,0.55)",
      color: "#fff",
      fontFamily: "Inter, system-ui, sans-serif",
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
    }}>
      <div style={{display: "flex", alignItems: "center", gap: 10, padding: "10px 14px"}}>
        <AlbumThumb artist={artist} album={album} track={title} seed={title + artist} size={44} radius={6}/>
        {/* Tap title to open lyrics. Buttoned for proper click semantics. */}
        <button
          onClick={() => setLyricsOpen(true)}
          aria-label="Show lyrics"
          style={{
            flex: 1, minWidth: 0,
            background: "transparent", border: "none", color: "inherit",
            textAlign: "left", padding: 0, cursor: "pointer",
          }}
        >
          <div style={{
            fontSize: 14, fontWeight: 700, letterSpacing: "-0.01em",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>{title}</div>
          <div style={{
            fontSize: 11, color: "rgba(255,255,255,0.6)",
            fontFamily: "'JetBrains Mono', monospace",
            letterSpacing: "0.04em",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            marginTop: 1,
          }}>
            {artist || (externalActive ? (ext.label ?? ext.source ?? "") : "")}
            {album ? ` · ${album}` : ""}
          </div>
        </button>
        <SourceBadge
          uri={externalActive ? null : (m.track?.uri ?? null)}
          externalLabel={externalActive ? (ext.label ?? ext.source ?? null) : null}
        />
        <div style={{display: "flex", alignItems: "center", gap: 4}}>
          <TransportBtn
            onClick={() => toggleFavorite(externalActive ? null : (m.track?.uri ?? null))}
            ariaLabel="Toggle favourite"
          >
            <span style={{
              color: (m.track?.uri && favs.has(m.track.uri)) ? "#ff5466" : "rgba(255,255,255,0.55)",
              fontSize: 16,
            }}>♥</span>
          </TransportBtn>
          <TransportBtn onClick={onPrev} ariaLabel="Previous">‹‹</TransportBtn>
          <TransportBtn onClick={onToggle} ariaLabel={playing ? "Pause" : "Play"} primary>
            {playing ? "❚❚" : "▶"}
          </TransportBtn>
          <TransportBtn onClick={onNext} ariaLabel="Next">››</TransportBtn>
          {onDismiss && (
            <button
              onClick={onDismiss}
              aria-label="Hide player"
              style={{
                width: 32, height: 32, marginLeft: 4,
                background: "transparent", border: 0, color: "rgba(255,255,255,0.55)",
                fontSize: 18, lineHeight: 1, cursor: "pointer",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}
            >
              ✕
            </button>
          )}
        </div>
      </div>
      {/* Volume strip — visible slider so the user doesn't have to discover
        * the right-edge gesture. Drag or tap to set; ⓧ to mute. */}
      <VolumeStrip value={vol.value} muted={vol.muted} onSet={vol.set} onMuteToggle={vol.toggleMute}/>
      {/* Position bar (visual only — there's a tappable scrubber inside skins). */}
      <div style={{height: 3, background: "rgba(255,255,255,0.10)"}}>
        <div style={{
          height: "100%", width: `${pct * 100}%`,
          background: "linear-gradient(90deg, #5be7ff, #b794ff)",
          transition: "width 0.18s linear",
        }}/>
      </div>
    </div>
    {lyricsOpen && (
      <LyricsDrawer artist={artist} title={title} onClose={() => setLyricsOpen(false)}/>
    )}
    </>
  );
}

// ---- system volume hook + visible slider ---------------------------------

function useSystemVolume() {
  const [value, setValue] = useState(0.5);
  const [muted, setMuted] = useState(false);
  const dragRef = useRef(false);

  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      try {
        const r = await fetch("/api/volume", { cache: "no-store" });
        if (!r.ok) return;
        const j = await r.json();
        if (!dragRef.current && !stopped) {
          if (typeof j.volume === "number") setValue(j.volume);
          setMuted(!!j.muted);
        }
      } catch { /* ignore */ }
    };
    tick();
    const id = setInterval(tick, 4000);
    return () => { stopped = true; clearInterval(id); };
  }, []);

  const set = async (v: number) => {
    const clamped = Math.max(0, Math.min(1, v));
    setValue(clamped);
    try {
      await fetch("/api/volume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ volume: clamped }),
      });
    } catch { /* optimistic */ }
  };

  const toggleMute = async () => {
    // We don't have a server "mute toggle"; emulate by setting to 0 / restoring.
    if (muted || value === 0) {
      await set(0.4);
      setMuted(false);
    } else {
      await set(0);
      setMuted(true);
    }
  };

  return { value, muted, set, toggleMute, dragRef };
}

function VolumeStrip({ value, muted, onSet, onMuteToggle }: {
  value: number; muted: boolean;
  onSet: (v: number) => void;
  onMuteToggle: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const dragging = useRef(false);

  const fractionFromEvent = (clientX: number): number => {
    const el = ref.current;
    if (!el) return 0;
    const r = el.getBoundingClientRect();
    if (r.width <= 0) return 0;
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width));
  };

  const onPointerDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    dragging.current = true;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    onSet(fractionFromEvent(e.clientX));
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    e.stopPropagation();
    onSet(fractionFromEvent(e.clientX));
  };
  const finish = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    dragging.current = false;
    try { (e.target as Element).releasePointerCapture?.(e.pointerId); } catch { /* noop */ }
  };

  const pct = Math.round((muted ? 0 : value) * 100);

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "8px 12px",
      borderTop: "1px solid rgba(255,255,255,0.10)",
    }}>
      <button
        onClick={onMuteToggle}
        aria-label={muted ? "Unmute" : "Mute"}
        style={{
          width: 36, height: 36,
          borderRadius: 999,
          background: "rgba(255,255,255,0.08)",
          border: "1px solid rgba(255,255,255,0.15)",
          color: "#fff",
          cursor: "pointer",
          fontSize: 14,
          display: "grid", placeItems: "center",
          flexShrink: 0,
        }}
      >{muted || value === 0 ? "🔇" : value < 0.4 ? "🔈" : value < 0.75 ? "🔉" : "🔊"}</button>
      <div
        ref={ref}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={finish}
        onPointerCancel={finish}
        style={{
          flex: 1, height: 32,                    // big touch hit area
          display: "flex", alignItems: "center",
          cursor: "pointer",
          touchAction: "none",
        }}
      >
        <div style={{
          width: "100%", height: 6,
          background: "rgba(255,255,255,0.12)",
          borderRadius: 3,
          position: "relative",
        }}>
          <div style={{
            position: "absolute", left: 0, top: 0, bottom: 0,
            width: `${pct}%`,
            background: "linear-gradient(90deg, #5be7ff, #b794ff)",
            borderRadius: 3,
            transition: "width 0.12s",
          }}/>
          <div style={{
            position: "absolute", left: `${pct}%`, top: -5,
            width: 14, height: 14, borderRadius: "50%",
            background: "#fff", transform: "translateX(-50%)",
            boxShadow: "0 0 0 1px rgba(0,0,0,0.4)",
          }}/>
        </div>
      </div>
      <div style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        color: "rgba(255,255,255,0.7)",
        width: 36, textAlign: "right",
        flexShrink: 0,
      }}>{pct}</div>
    </div>
  );
}

function TransportBtn({ children, onClick, primary, ariaLabel }: {
  children: React.ReactNode;
  onClick?: () => void;
  primary?: boolean;
  ariaLabel: string;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={ariaLabel}
      style={{
        width: 44, height: 44,
        borderRadius: 999,
        background: primary ? "#fff" : "rgba(255,255,255,0.08)",
        color: primary ? "#000" : "#fff",
        border: primary ? "none" : "1px solid rgba(255,255,255,0.15)",
        cursor: "pointer",
        fontSize: primary ? 14 : 16,
        fontWeight: 700,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >{children}</button>
  );
}

// SourceBadge — tiny pill next to the title that tells the user which
// pipeline is currently delivering audio: cache vs stream vs USB vs an
// external MPRIS source (AirPlay / Spotify / Bluetooth).
function SourceBadge({ uri, externalLabel }: { uri: string | null; externalLabel: string | null }) {
  let glyph = "🎵"; let label = "USB";
  if (externalLabel) {
    if (/airplay/i.test(externalLabel))         { glyph = "📱"; label = "AirPlay"; }
    else if (/spotify/i.test(externalLabel))    { glyph = "🎵"; label = "Spotify"; }
    else if (/bluetooth/i.test(externalLabel))  { glyph = "🎙"; label = "BT"; }
    else                                         { glyph = "🎵"; label = externalLabel; }
  } else if (uri) {
    if (uri.startsWith("file://"))           { glyph = "⬇"; label = "Cache"; }
    else if (uri.startsWith("subsonic:"))    { glyph = "⚡"; label = "Stream"; }
    else if (uri.startsWith("spotify:"))     { glyph = "🎵"; label = "Spotify"; }
    else if (uri.startsWith("local:"))       { glyph = "🎵"; label = "USB"; }
  }
  return (
    <span
      title={`Source · ${label}`}
      style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "2px 8px",
        background: "rgba(255,255,255,0.08)",
        border: "1px solid rgba(255,255,255,0.14)",
        borderRadius: 999,
        fontSize: 11,
        fontFamily: "'JetBrains Mono', monospace",
        letterSpacing: "0.08em",
        color: "rgba(255,255,255,0.78)",
        flexShrink: 0,
      }}
    >
      <span aria-hidden="true">{glyph}</span>
      <span>{label.toUpperCase()}</span>
    </span>
  );
}
