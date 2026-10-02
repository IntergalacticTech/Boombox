// NIGHTSTAND — bedside face for dark rooms; ember on near-black, one big button.
//
// Design: "Boombox Skins" canvas, artboard 1d. Low overall luminance keeps
// panel power and heat down. Motion is limited to two one-shot transitions:
// the big ring fills ember on pause (opacity, 300 ms) and the track details
// fade to 45 % (opacity, 400 ms). No glow, no breathing, nothing continuous.
import React from "react";
import { mmss } from "../../lib/shared";
import { SeekableBar } from "../../lib/SeekableBar";
import { useAlbumArt } from "../../lib/albumArt";
import type { SkinAudioProps, SkinTheme } from "../../lib/skinRegistry";
import type { Track } from "../../lib/types";

const C = {
  bg:     "#0B0807",
  panel:  "#171110",
  ink:    "#F2A48C",
  ink2:   "#B87563",
  title:  "#F7B7A2",
  ember:  "#FF5A36",
  amber:  "#FFB347",
  rule:   "#2A1D1A",
  edge:   "#3A2824",
  font:   "'Red Hat Display', system-ui, -apple-system, sans-serif",
  mono:   "'Red Hat Mono', 'JetBrains Mono', ui-monospace, monospace",
};

export const NIGHTSTAND_THEME: SkinTheme = {
  bg: C.bg, panel: C.panel, ink: C.ink, ink2: C.ink2,
  accent: C.ember, accent2: C.amber, rule: C.rule,
  font: C.font, mono: C.mono,
};

export const NIGHTSTAND_SWATCH: string[] = [C.bg, C.ember, C.ink, C.amber];

/** Grey dot for an unknown source (no chrome, e.g. the skin-picker preview). */
const UNKNOWN_SRC = "#8A8A8A";

const RING_FILL_MS = 300;
const DETAILS_FADE_MS = 400;

function PrevGlyph() {
  return <svg width="40" height="40" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h2.5v14H6zM20 5v14L9 12z" fill={C.ink}/></svg>;
}
function NextGlyph() {
  return <svg width="40" height="40" viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 5H18v14h-2.5zM4 5v14l11-7z" fill={C.ink}/></svg>;
}

const resetBtn: React.CSSProperties = {
  appearance: "none", background: "transparent", border: "none", padding: 0, margin: 0,
  font: "inherit", color: "inherit", cursor: "pointer",
};

/** Album art: track.artUrl when set, else the shared /api/art lookup the
 *  other skins use; if neither yields a cover (or it fails to load), a soft
 *  radial disc from the track's hue with the album/title initial. */
function Art({ track, initial }: { track: Track; initial: string }) {
  // Keyed by track uri at the call site, so a failed load resets per track.
  const [failed, setFailed] = React.useState(false);
  const own = track.artUrl;
  const looked = useAlbumArt(own ? null : track.artist, own ? null : track.album, own ? null : track.title);
  const url = own || looked || undefined;
  const hue = track.hue;
  if (url && !failed) {
    return (
      <img src={url} alt="" width={120} height={120} decoding="async"
        onError={() => setFailed(true)}
        style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}/>
    );
  }
  return (
    <div data-testid="nightstand-art-fallback" style={{
      width: "100%", height: "100%",
      background: `radial-gradient(circle at 30% 30%, oklch(0.68 0.13 ${hue}), oklch(0.42 0.1 ${hue}))`,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: 56, fontWeight: 700, color: C.bg,
    }}>{initial}</div>
  );
}

export function NightstandAudio({
  track, state, elapsed, volume, shuffle = false, repeat = false, chrome,
  onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek,
}: SkinAudioProps) {
  const playing = state === "playing";
  const hasTrack = !!track;
  const paused = hasTrack && !playing;
  const source = chrome?.sourceLabel ?? "";
  const srcColor = chrome?.sourceColor ?? UNKNOWN_SRC;
  const aux = !hasTrack && source === "AUX";
  const idle = !hasTrack && !aux;
  const len = track && track.len > 0 ? track.len : 0;
  // LIVE is radio only: a length-less stream playing through Mopidy (the
  // LIBRARY source). External sources (AirPlay, Spotify, Bluetooth) set
  // chrome.sourceLive too, but they are not "live radio".
  const fromLibrary = !chrome || source === "LIBRARY";
  const live = hasTrack && len === 0 && playing && fromLibrary;
  const el = Math.max(0, len ? Math.min(len, elapsed) : elapsed);
  const pct = len ? el / len : 0;
  const showTime = hasTrack && (len > 0 || live);

  const title = track ? track.title : idle ? "Nothing queued" : "Line-in";
  const artist = track ? track.artist : idle ? "Open the Library to choose music" : "Playing from the AUX jack";
  const album = track?.album ?? "";
  const initial = ((track?.album || track?.title || "?").trim()[0] ?? "?").toUpperCase();
  const word = playing ? "PLAYING" : paused ? "PAUSED" : idle ? "" : "LINE-IN";
  const ctlOp = hasTrack ? 1 : 0.35;
  const seekable = len > 0 && !!onSeek;

  const nav = chrome;
  const pillOn = (on: boolean) => ({
    border: `2px solid ${on ? C.ember : C.edge}`,
    color: on ? C.ember : C.ink2,
  });

  return (
    <div data-skin="nightstand" style={{
      width: 1280, height: 800, overflow: "hidden", position: "relative",
      background: C.bg, color: C.ink, fontFamily: C.font,
    }}>
      {/* The one big button. The ember fill is an overlay whose opacity
        * transitions, so the pause/play change is compositor-only. */}
      <button
        aria-label={playing ? "Pause" : "Play"}
        onClick={onToggle}
        disabled={!hasTrack}
        style={{
          ...resetBtn,
          position: "absolute", left: 110, top: 150, width: 300, height: 300,
          boxSizing: "border-box", borderRadius: "50%", border: `4px solid ${C.ember}`,
          display: "flex", alignItems: "center", justifyContent: "center",
          opacity: ctlOp, cursor: hasTrack ? "pointer" : "default",
        }}
      >
        <span aria-hidden="true" style={{
          position: "absolute", inset: -4, borderRadius: "50%", background: C.ember,
          opacity: paused ? 1 : 0, transition: `opacity ${RING_FILL_MS}ms ease`,
        }}/>
        <svg width="120" height="120" viewBox="0 0 24 24" aria-hidden="true" style={{ position: "relative" }}>
          {playing
            ? <path d="M6 4h4v16H6zM14 4h4v16h-4z" fill={C.ember}/>
            : <path d="M7 4l13 8-13 8z" fill={paused ? C.bg : C.ember}/>}
        </svg>
      </button>

      <div aria-live="polite" style={{
        position: "absolute", left: 110, top: 470, width: 300, height: 48,
        textAlign: "center", fontSize: 36, fontWeight: 700, letterSpacing: "0.12em",
        color: C.ember, lineHeight: "48px",
      }}>{word}</div>

      <div style={{
        position: "absolute", left: 110, top: 540, width: 300,
        display: "flex", justifyContent: "space-between", opacity: ctlOp,
      }}>
        {[
          { label: "Previous", fn: onPrev, glyph: <PrevGlyph/> },
          { label: "Next", fn: onNext, glyph: <NextGlyph/> },
        ].map(b => (
          <button key={b.label} aria-label={b.label} onClick={b.fn} disabled={!hasTrack} style={{
            ...resetBtn,
            width: 120, height: 96, boxSizing: "border-box", borderRadius: 48,
            border: `2px solid ${C.edge}`,
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: hasTrack ? "pointer" : "default",
          }}>{b.glyph}</button>
        ))}
      </div>

      {/* Track details: drop to 45 % while paused. */}
      <div data-testid="nightstand-info" style={{
        position: "absolute", left: 500, top: 150, width: 700,
        display: "flex", flexDirection: "column", gap: 14,
        opacity: paused ? 0.45 : 1, transition: `opacity ${DETAILS_FADE_MS}ms ease`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 24, height: 120 }}>
          <div style={{
            width: 120, height: 120, borderRadius: 14, overflow: "hidden", flexShrink: 0, opacity: 0.8,
            boxSizing: "border-box", border: track ? "none" : `2px solid ${C.edge}`,
          }}>
            {track && <Art key={track.uri} track={track} initial={initial}/>}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 12,
              fontFamily: C.mono, fontSize: 24, fontWeight: 500, lineHeight: 1, letterSpacing: "0.08em",
            }}>
              {source && <span style={{ width: 14, height: 14, borderRadius: "50%", background: srcColor, flexShrink: 0 }}/>}
              {source && <span style={{ color: srcColor }}>{source}</span>}
              {live && <span style={{ color: C.amber }}>LIVE</span>}
            </div>
            <div style={{
              fontSize: 26, color: C.ink2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>{album}</div>
          </div>
        </div>

        <div style={{
          fontSize: 60, fontWeight: 700, lineHeight: 1.08, height: 130,
          display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2, overflow: "hidden",
          color: C.title, textWrap: "pretty", overflowWrap: "anywhere",
        }}>{title}</div>

        <div style={{
          fontSize: 34, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{artist}</div>

        <div style={{
          display: "grid", gridTemplateColumns: "90px 1fr 90px", gap: 18, alignItems: "center",
          fontFamily: C.mono, fontSize: 24, lineHeight: 1, fontVariantNumeric: "tabular-nums", color: C.ink2,
          opacity: len ? 1 : 0.35,
        }}>
          <span data-testid="nightstand-elapsed">{showTime ? mmss(el) : ""}</span>
          <div
            data-testid="nightstand-seek"
            role="group"
            aria-label="Seek"
            aria-disabled={!seekable}
            style={{ height: 72, display: "flex", alignItems: "center" }}
          >
            <SeekableBar value={pct} lengthSec={len} onSeek={seekable ? onSeek : undefined} hitHeight={68} style={{ width: "100%" }}>
              <div style={{ width: "100%", height: 4, borderRadius: 2, background: C.rule, overflow: "hidden" }}>
                <div style={{
                  height: "100%", borderRadius: 2, background: C.ember,
                  width: "calc(var(--seek-fraction, 0) * 100%)",
                }}/>
              </div>
            </SeekableBar>
          </div>
          <span style={{ textAlign: "right" }}>{len ? mmss(len) : showTime ? "LIVE" : ""}</span>
        </div>

        <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
          <button aria-label="Shuffle" aria-pressed={shuffle} onClick={onToggleShuffle} style={{
            ...resetBtn, height: 72, padding: "0 28px", borderRadius: 36, boxSizing: "border-box",
            ...pillOn(shuffle), display: "flex", alignItems: "center", fontSize: 24, fontWeight: 700,
          }}>Shuffle</button>
          <button aria-label="Repeat" aria-pressed={repeat} onClick={onToggleRepeat} style={{
            ...resetBtn, height: 72, padding: "0 28px", borderRadius: 36, boxSizing: "border-box",
            ...pillOn(repeat), display: "flex", alignItems: "center", fontSize: 24, fontWeight: 700,
          }}>Repeat</button>
          {volume != null && (
            <div style={{
              paddingLeft: 12, fontFamily: C.mono, fontSize: 24, lineHeight: 1, color: C.ink2,
              fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap",
            }}>{`VOL ${Math.round(volume)}`}</div>
          )}
        </div>
      </div>

      {/* Navigation: always visible along the bottom edge. */}
      <nav aria-label="Navigation" style={{
        position: "absolute", left: 110, top: 712, width: 1090, height: 72,
        display: "flex", gap: 8, fontSize: 26, fontWeight: 500, color: C.ink2,
      }}>
        <button aria-label="Home" onClick={nav?.onGoHome} disabled={!nav} style={{
          ...resetBtn, flex: 1.3, minWidth: 0, display: "flex", alignItems: "center", gap: 12,
          whiteSpace: "nowrap", overflow: "hidden",
        }}>
          <span style={{ width: 14, height: 14, borderRadius: "50%", background: srcColor, flexShrink: 0 }}/>
          <span style={{ flexShrink: 0 }}>{source ? "Home ·" : "Home"}</span>
          {source && <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{source}</span>}
        </button>
        <button aria-label="Library" onClick={nav?.onOpenLibrary} disabled={!nav} style={{
          ...resetBtn, flex: 1, minWidth: 0, display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <span style={{
            padding: "12px 22px", borderRadius: 30,
            background: idle ? C.ember : "transparent", color: idle ? C.bg : C.ink2,
          }}>Library</span>
        </button>
        <button aria-label="Queue" onClick={nav?.onOpenQueue} disabled={!nav} style={{
          ...resetBtn, flex: 1, minWidth: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
          whiteSpace: "nowrap",
        }}>
          Queue{nav && <span style={{ color: C.ink, fontVariantNumeric: "tabular-nums" }}>{nav.queueCount}</span>}
        </button>
        <button aria-label="Skin" onClick={nav?.onOpenSkinPicker} disabled={!nav} style={{
          ...resetBtn, flex: 1.2, minWidth: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
          whiteSpace: "nowrap", overflow: "hidden",
        }}>
          Skin <span style={{ color: C.ink, overflow: "hidden", textOverflow: "ellipsis" }}>{nav?.skinName ?? "Nightstand"}</span>
        </button>
        <button aria-label="Settings" onClick={nav?.onOpenSettings} disabled={!nav} style={{
          ...resetBtn, flex: 1, minWidth: 0, display: "flex", alignItems: "center", justifyContent: "flex-end",
        }}>Settings</button>
      </nav>
    </div>
  );
}
