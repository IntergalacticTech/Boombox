// POCKET LCD — reflective calculator LCD with ghost segments and rubber keys.
//
// Every annunciator is always printed; state is shown purely by which ones
// are dark (lit) versus ghosted, the way a real segment LCD works. Nothing
// animates: segments switch instantly when values change, and the rubber
// keys only depress 4 px (transform, 80 ms) while a finger is on them.
import React from "react";
import { useAlbumArt } from "../../lib/albumArt";
import type { SkinAudioProps, SkinTheme } from "../../lib/skinRegistry";

const LCD = {
  body:    "#2B2D29",
  glass:   "#B9C3A5",
  ink:     "#1A2015",
  ink2:    "#3E4836",
  hatchA:  "#a6b192",
  hatchB:  "#9ca787",
  rule:    "#93A07F",
  accent:  "#C9502F",
  accentHi:"#e07a5c",
  live:    "#8C2F1F",
  key:     "#41443E",
  keyOn:   "#5E6358",
  keyHi:   "#5a5e56",
  keyShadow: "#1b1c19",
  keyInk:  "#E6E8E0",
  keyInk2: "#C7CBBE",
  lcdFont: "'Share Tech Mono', 'JetBrains Mono', ui-monospace, monospace",
  keyFont: "'Chakra Petch', 'Barlow Condensed', system-ui, sans-serif",
};

export const POCKETLCD_THEME: SkinTheme = {
  bg: LCD.glass, panel: LCD.body, ink: LCD.ink, ink2: LCD.ink2,
  accent: LCD.accent, accent2: LCD.live,
  rule: LCD.rule,
  font: LCD.keyFont, mono: LCD.lcdFont,
};

export const POCKETLCD_SWATCH: string[] = [LCD.body, LCD.glass, LCD.ink, LCD.accent];

/** Opacity of an unlit ("ghost") segment. */
const GHOST = 0.14;
/** Number of cells in the segmented progress bar. */
const CELLS = 48;

/** The annunciators the LCD prints, in order. */
const SOURCES: { id: string; short: string }[] = [
  { id: "LIBRARY",   short: "LIBRARY" },
  { id: "AIRPLAY",   short: "AIRPLAY" },
  { id: "SPOTIFY",   short: "SPOTIFY" },
  { id: "BLUETOOTH", short: "BLUETOOTH" },
  { id: "AUX",       short: "AUX" },
];
/** Short form printed on the Home key under "HOME". */
const KEY_SHORT: Record<string, string> = {
  LIBRARY: "LIB", AIRPLAY: "AIR", SPOTIFY: "SPOT", BLUETOOTH: "BT", AUX: "AUX", IDLE: "—", VIDEO: "VID",
};

/** mm:ss with a two-digit minute, the LCD's native format. */
function pad(s: number): string {
  s = Math.max(0, Math.floor(s));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** Key press feedback and the visually-hidden helper, scoped to this skin. */
const CSS = `
.plcd-key{transition:transform 80ms linear;-webkit-tap-highlight-color:transparent}
.plcd-key:not(:disabled):active{transform:translateY(4px)}
.plcd-key:focus-visible{outline:3px solid ${LCD.glass};outline-offset:3px}
`;

type KeyProps = {
  label: string;
  onClick?: () => void;
  width?: number;
  height?: number;
  bg?: string;
  hi?: string;
  radius?: number;
  dim?: boolean;
  pressed?: boolean;
  children: React.ReactNode;
};

/** A rubber calculator key. Disabled (but still drawn) when it has no action. */
function Key({ label, onClick, width = 104, height = 120, bg = LCD.key, hi = LCD.keyHi, radius = 16, dim, pressed, children }: KeyProps) {
  return (
    <button
      type="button"
      className="plcd-key"
      aria-label={label}
      aria-pressed={pressed}
      onClick={onClick}
      disabled={!onClick}
      style={{
        width, height, borderRadius: radius, flexShrink: 0,
        background: bg, border: "none", padding: 0, margin: 0,
        boxShadow: `inset 0 2px 0 ${hi}, 0 4px 0 ${LCD.keyShadow}`,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8,
        fontFamily: LCD.keyFont, fontWeight: 600, fontSize: 22, color: LCD.keyInk,
        cursor: onClick ? "pointer" : "default",
        opacity: dim ? 0.35 : 1,
      }}
    >{children}</button>
  );
}

/** Segmented progress bar; tap or drag to seek when the length is known. */
function CellBar({ fraction, lengthSec, onSeek, dim }: { fraction: number; lengthSec: number; onSeek?: (sec: number) => void; dim: boolean }) {
  const ref = React.useRef<HTMLDivElement | null>(null);
  const [drag, setDrag] = React.useState<number | null>(null);
  const interactive = !!onSeek && lengthSec > 0;

  const at = (clientX: number) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r || r.width <= 0) return 0;
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width));
  };
  const finish = (e: React.PointerEvent) => {
    if (drag === null) return;
    try { (e.target as Element).releasePointerCapture?.(e.pointerId); } catch { /* noop */ }
    onSeek?.(drag * lengthSec);
    setDrag(null);
  };

  const shown = drag ?? fraction;
  const filled = lengthSec > 0 ? Math.round(shown * CELLS) : 0;
  return (
    <div
      ref={ref}
      role="slider"
      aria-label="Seek"
      aria-valuemin={0}
      aria-valuemax={Math.max(0, Math.round(lengthSec))}
      aria-valuenow={Math.round(shown * lengthSec)}
      aria-disabled={!interactive}
      data-testid="plcd-seek"
      onPointerDown={interactive ? e => {
        (e.target as Element).setPointerCapture?.(e.pointerId);
        setDrag(at(e.clientX));
      } : undefined}
      onPointerMove={interactive ? e => { if (drag !== null) setDrag(at(e.clientX)); } : undefined}
      onPointerUp={interactive ? finish : undefined}
      onPointerCancel={interactive ? () => setDrag(null) : undefined}
      style={{
        position: "absolute", left: 40, top: 440, width: 1128, height: 72,
        display: "flex", alignItems: "center", gap: 4,
        cursor: interactive ? "pointer" : "default",
        touchAction: "none", userSelect: "none",
        opacity: dim ? 0.35 : 1,
      }}
    >
      {Array.from({ length: CELLS }, (_, i) => (
        <div key={i} style={{ flex: 1, height: 26, background: LCD.ink, opacity: i < filled ? 1 : GHOST }}/>
      ))}
    </div>
  );
}

/** Cover art window: real art, the dot-screen fallback, or the empty label. */
function ArtWindow({ track, emptyLabel, onEmptyClick }: {
  track: SkinAudioProps["track"]; emptyLabel: string; onEmptyClick?: () => void;
}) {
  const looked = useAlbumArt(track && !track.artUrl ? track.artist : null, track && !track.artUrl ? track.album : null, track && !track.artUrl ? track.title : null);
  const url = track ? (track.artUrl ?? looked) : null;
  const [failed, setFailed] = React.useState<string | null>(null);
  const showImg = !!url && failed !== url;

  const box: React.CSSProperties = {
    position: "absolute", left: 868, top: 96, width: 300, height: 300,
    border: `3px solid ${LCD.ink}`, boxSizing: "border-box", overflow: "hidden",
  };
  if (!track) {
    const inner: React.CSSProperties = {
      width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center",
      textAlign: "center", fontSize: 34, lineHeight: 1.2, padding: 20, boxSizing: "border-box",
      fontFamily: LCD.lcdFont, color: LCD.ink,
    };
    return (
      <div style={box}>
        {onEmptyClick
          ? <button type="button" onClick={onEmptyClick} aria-label={emptyLabel}
              style={{ ...inner, background: "transparent", border: "none", cursor: "pointer", margin: 0 }}>{emptyLabel}</button>
          : <div style={inner}>{emptyLabel}</div>}
      </div>
    );
  }
  if (showImg) {
    return (
      <div style={box}>
        <img src={url!} alt="" width={294} height={294} decoding="async"
          onError={() => setFailed(url)}
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}/>
      </div>
    );
  }
  const initial = ((track.album || track.title || "?").trim()[0] ?? "?").toUpperCase();
  return (
    <div style={box} data-testid="plcd-fallback-art">
      <div style={{
        width: "100%", height: "100%",
        background: `oklch(0.68 0.13 ${track.hue})`,
        backgroundImage: `radial-gradient(${LCD.ink}40 1.5px, transparent 1.6px)`,
        backgroundSize: "8px 8px",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: LCD.lcdFont, fontSize: 180, lineHeight: 1, color: LCD.ink,
      }}>{initial}</div>
    </div>
  );
}

export function PocketLcdAudio({
  track, state, elapsed, volume, shuffle = false, repeat = false, chrome,
  onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek,
}: SkinAudioProps) {
  const playing = state === "playing";
  const paused = !!track && state === "paused";
  const stopped = !track || state === "stopped";
  const source = chrome?.sourceLabel ?? "";
  const isAux = !track && source === "AUX";
  const isIdle = !track && !isAux;
  const len = track && track.len > 0 ? track.len : 0;
  // Radio: a length-less stream playing from the library. External sources
  // (AirPlay, Spotify, Bluetooth) are never "live" here, as in the design.
  const live = !!track && len === 0 && playing && (!chrome || chrome.sourceLabel === "LIBRARY");
  const showTime = !!track && (len > 0 || (live && elapsed > 0));
  const time = showTime ? pad(len > 0 ? Math.min(elapsed, len) : elapsed) : "";
  const ghostTime = time ? time.replace(/\d/g, "8") : "88:88";
  const fraction = len > 0 ? Math.max(0, Math.min(1, elapsed / len)) : 0;

  const title = track ? track.title : isAux ? "Line-in" : "Nothing queued";
  const artist = track ? track.artist : isAux ? "Playing from the AUX jack" : "Open the Library to choose music";
  const knownSource = SOURCES.some(s => s.id === source);
  const extraSource = chrome && !knownSource && source && source !== "IDLE" ? source : null;
  const volStr = volume != null ? `VOL ${String(Math.round(volume)).padStart(3, " ")}` : "VOL";
  const skinName = (chrome?.skinName ?? "").toUpperCase();

  return (
    <div style={{
      width: 1280, height: 800, overflow: "hidden", position: "relative",
      background: LCD.body, color: LCD.ink, fontFamily: LCD.lcdFont,
    }}>
      <style>{CSS}</style>

      {/* ── LCD glass ─────────────────────────────────────────── */}
      <div style={{
        position: "absolute", left: 32, top: 24, width: 1216, height: 572, borderRadius: 14,
        background: LCD.glass, boxShadow: "inset 0 3px 10px rgba(0,0,0,.35)",
      }}>
        <div style={{ position: "absolute", left: 40, top: 28, display: "flex", gap: 28, fontSize: 26, letterSpacing: ".06em" }}>
          <span data-lit={playing} style={{ opacity: playing ? 1 : GHOST }}>PLAY</span>
          <span data-lit={paused} style={{ opacity: paused ? 1 : GHOST }}>PAUSE</span>
          <span data-lit={stopped} style={{ opacity: stopped ? 1 : GHOST }}>STOP</span>
        </div>

        <div style={{ position: "absolute", left: 40, top: 76, height: 210, display: "flex", alignItems: "flex-end", gap: 24 }}>
          <div aria-label={time ? `Elapsed ${time}` : undefined} style={{
            display: "grid", fontSize: 196, lineHeight: 1, letterSpacing: 0, whiteSpace: "pre",
            fontVariantNumeric: "tabular-nums",
          }}>
            <span aria-hidden="true" style={{ gridArea: "1/1", opacity: 0.1 }}>{ghostTime}</span>
            <span style={{ gridArea: "1/1" }}>{time}</span>
          </div>
          <div style={{ fontSize: 44, paddingBottom: 22, color: LCD.ink2, fontVariantNumeric: "tabular-nums" }}>
            {len > 0 ? `/${pad(len)}` : ""}
          </div>
        </div>

        <ArtWindow
          track={track}
          emptyLabel={isAux ? "AUX in" : "Open Library"}
          onEmptyClick={isIdle ? chrome?.onOpenLibrary : undefined}
        />

        <div data-testid="plcd-title" title={title} style={{
          position: "absolute", left: 40, top: 306, width: 790, fontSize: 44, lineHeight: 1.1,
          textTransform: "uppercase", display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2,
          overflow: "hidden", overflowWrap: "anywhere",
          // Two lines of 44 px must clear the artist row at 410.
          maxHeight: 97,
        }}>{title}</div>
        <div data-testid="plcd-artist" style={{
          position: "absolute", left: 40, top: 410, width: 790, fontSize: 30, color: LCD.ink2,
          textTransform: "uppercase", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{artist}</div>

        <CellBar fraction={fraction} lengthSec={len} onSeek={onSeek} dim={len === 0}/>

        <div style={{
          position: "absolute", left: 40, top: 520, width: 1128, display: "flex", gap: 22,
          fontSize: 24, letterSpacing: ".04em", whiteSpace: "pre",
        }}>
          {SOURCES.map(s => (
            <span key={s.id} data-lit={source === s.id} style={{ opacity: source === s.id ? 1 : GHOST }}>{s.short}</span>
          ))}
          {extraSource && <span data-lit="true">{extraSource}</span>}
          <span data-lit={live} style={{ color: LCD.live, opacity: live ? 1 : GHOST }}>LIVE</span>
          <span style={{ flex: 1 }}/>
          <span data-lit={shuffle} style={{ opacity: shuffle ? 1 : GHOST }}>SHUF</span>
          <span data-lit={repeat} style={{ opacity: repeat ? 1 : GHOST }}>RPT</span>
          <span data-lit={volume != null} style={{ opacity: volume != null ? 1 : GHOST, fontVariantNumeric: "tabular-nums" }}>{volStr}</span>
        </div>
      </div>

      {/* ── Rubber keys ───────────────────────────────────────── */}
      <div style={{
        position: "absolute", left: 44, top: 624, width: 1192, height: 144,
        display: "flex", alignItems: "center", gap: 10,
      }}>
        <Key label="Home" onClick={chrome?.onGoHome}>
          <span>HOME</span>
          {chrome && (
            <span style={{ display: "flex", alignItems: "center", gap: 6, color: LCD.keyInk2 }}>
              <span style={{ width: 12, height: 12, borderRadius: "50%", background: chrome.sourceColor }}/>
              {KEY_SHORT[source] ?? source.slice(0, 4)}
            </span>
          )}
        </Key>
        <Key label="Library" onClick={chrome?.onOpenLibrary} bg={isIdle ? LCD.accent : LCD.key} hi={isIdle ? LCD.accentHi : LCD.keyHi}>
          <span>LIBRARY</span>
        </Key>
        <Key label="Queue" onClick={chrome?.onOpenQueue}>
          <span>QUEUE</span>
          {chrome && <span style={{ color: LCD.keyInk2, fontVariantNumeric: "tabular-nums" }}>{chrome.queueCount}</span>}
        </Key>
        <Key label="Skin" onClick={chrome?.onOpenSkinPicker}>
          <span>SKIN</span>
          {chrome && skinName && (
            <span style={{
              color: LCD.keyInk2, fontSize: skinName.length > 6 ? 14 : 22, maxWidth: 92,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>{skinName}</span>
          )}
        </Key>
        <Key label="Settings" onClick={chrome?.onOpenSettings}><span>SET</span></Key>

        <div style={{ flex: 1 }}/>

        <Key label="Shuffle" width={96} onClick={onToggleShuffle} pressed={shuffle} bg={shuffle ? LCD.keyOn : LCD.key}>
          <span>SHUF</span>
        </Key>
        <Key label="Previous" onClick={onPrev} dim={!track}>
          <svg width="40" height="40" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h2.5v14H6zM20 5v14L9 12z" fill={LCD.keyInk}/></svg>
        </Key>
        <Key label={playing ? "Pause" : "Play"} onClick={onToggle} width={176} height={136} radius={18}
          bg={LCD.accent} hi={LCD.accentHi} dim={!track}>
          {playing
            ? <svg width="64" height="64" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h4v16H6zM14 4h4v16h-4z" fill="#FFFFFF"/></svg>
            : <svg width="64" height="64" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z" fill="#FFFFFF"/></svg>}
        </Key>
        <Key label="Next" onClick={onNext} dim={!track}>
          <svg width="40" height="40" viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 5H18v14h-2.5zM4 5v14l11-7z" fill={LCD.keyInk}/></svg>
        </Key>
        <Key label="Repeat" width={96} onClick={onToggleRepeat} pressed={repeat} bg={repeat ? LCD.keyOn : LCD.key}>
          <span>RPT</span>
        </Key>
      </div>
    </div>
  );
}
