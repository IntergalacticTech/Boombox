// PLACARD — "Gallery wall; the cover hung as a work, the track as its label."
// Design: Boombox Skins.dc.html, artboard 1b.
//
// Motion budget (Pi 5, no fan): the label cross-fades once on track change
// (240 ms) and the artwork fades in once when it loads (400 ms), both
// opacity-only and one-shot. The seek knob steps with the elapsed prop.
// Nothing runs continuously, whatever the play state.
import React from "react";
import { mmss } from "../../lib/shared";
import { SeekableBar } from "../../lib/SeekableBar";
import { useAlbumArt } from "../../lib/albumArt";
import type { SkinAudioProps, SkinTheme } from "../../lib/skinRegistry";
import type { Track } from "../../lib/types";

const C = {
  bg:     "#ECE7DD",
  panel:  "#FFFFFF",
  ink:    "#1D1B18",
  ink2:   "#5E5850",
  accent: "#9C2F22",   // oxblood
  accent2:"#2F5D50",
  rule:   "#CFC8BC",
  serif:  "'Newsreader', 'Iowan Old Style', Georgia, 'Times New Roman', serif",
  mono:   "'IBM Plex Mono', 'JetBrains Mono', ui-monospace, monospace",
};

export const PLACARD_THEME: SkinTheme = {
  bg: C.bg, panel: C.panel, ink: C.ink, ink2: C.ink2,
  accent: C.accent, accent2: C.accent2, rule: C.rule,
  font: C.serif, mono: C.mono,
};

export const PLACARD_SWATCH: string[] = ["#ECE7DD", "#FFFFFF", "#1D1B18", "#9C2F22"];

/** One-shot fades. Defined once; only opacity animates. */
const KEYFRAMES = `@keyframes placard-fade{from{opacity:0}to{opacity:1}}`;

const LABEL_FONT: React.CSSProperties = {
  fontFamily: C.mono, fontWeight: 500, fontSize: 22, lineHeight: 1, letterSpacing: "0.08em",
};

function titleCase(s: string): string {
  return s ? s.charAt(0) + s.slice(1).toLowerCase() : s;
}

// ── Artwork ──────────────────────────────────────────────────────────────

function Artwork({ track }: { track: Track }) {
  const looked = useAlbumArt(
    track.artUrl ? null : track.artist,
    track.artUrl ? null : track.album,
    track.artUrl ? null : track.title,
  );
  const url = track.artUrl ?? looked;
  const [loadedUrl, setLoadedUrl] = React.useState<string | null>(null);
  const [failedUrl, setFailedUrl] = React.useState<string | null>(null);
  const showImg = !!url && failedUrl !== url;

  if (!showImg) return <MissingArt track={track}/>;
  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      {/* The tinted mat shows until the picture has loaded. */}
      <MissingArt track={track}/>
      <img
        src={url}
        alt=""
        decoding="async"
        onLoad={() => setLoadedUrl(url)}
        onError={() => setFailedUrl(url)}
        style={{
          position: "absolute", inset: 0, width: "100%", height: "100%",
          objectFit: "cover", display: "block",
          opacity: loadedUrl === url ? 1 : 0,
          transition: "opacity 400ms ease-out",
        }}
      />
    </div>
  );
}

/** Missing art: a tinted mat with a coloured disc and an italic initial. */
function MissingArt({ track }: { track: Track }) {
  const initial = ((track.album || track.title || "?").trim().charAt(0) || "?").toUpperCase();
  const h = track.hue;
  return (
    <div data-testid="placard-missing-art" style={{
      width: "100%", height: "100%", background: `oklch(0.9 0.04 ${h})`,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div aria-hidden="true" style={{
        width: "62%", height: "62%", borderRadius: "50%", background: `oklch(0.68 0.13 ${h})`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: C.serif, fontStyle: "italic", fontWeight: 400, fontSize: 150, lineHeight: 1,
        color: "#FFFFFF",
      }}>{initial}</div>
    </div>
  );
}

// ── Icons (as drawn on the artboard) ─────────────────────────────────────

const PrevGlyph = () => (
  <svg width="36" height="36" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h2.5v14H6zM20 5v14L9 12z" fill={C.ink}/></svg>
);
const NextGlyph = () => (
  <svg width="36" height="36" viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 5H18v14h-2.5zM4 5v14l11-7z" fill={C.ink}/></svg>
);
const PauseGlyph = () => (
  <svg width="48" height="48" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h4v16H6zM14 4h4v16h-4z" fill="#FFFFFF"/></svg>
);
const PlayGlyph = () => (
  <svg width="48" height="48" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z" fill="#FFFFFF"/></svg>
);

const BTN_RESET: React.CSSProperties = {
  margin: 0, padding: 0, border: "none", background: "transparent", color: "inherit",
  font: "inherit", cursor: "pointer", WebkitTapHighlightColor: "transparent",
};

function Pill({ label, on, onClick }: { label: string; on: boolean; onClick?: () => void }) {
  return (
    <button
      type="button"
      aria-label={titleCase(label)}
      aria-pressed={on}
      onClick={onClick}
      style={{
        ...BTN_RESET, ...LABEL_FONT,
        height: 76, padding: "0 28px", borderRadius: 38, boxSizing: "border-box",
        border: `2px solid ${C.ink}`,
        background: on ? C.ink : "transparent", color: on ? "#FFFFFF" : C.ink,
        display: "flex", alignItems: "center", flexShrink: 0,
      }}
    >{label}</button>
  );
}

// ── Skin ─────────────────────────────────────────────────────────────────

export function PlacardAudio({
  track, state, elapsed, volume, shuffle = false, repeat = false, chrome,
  onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek,
}: SkinAudioProps) {
  const playing = state === "playing";
  const source = chrome?.sourceLabel ?? (track ? "LIBRARY" : "IDLE");
  const srcColor = chrome?.sourceColor ?? C.rule;
  const external = !!chrome?.sourceLive;
  const isAux = !track && source === "AUX";
  // No track and no external source feeding the speakers: nothing queued.
  const isIdle = !track && !isAux && (!external || source === "IDLE");
  // Tracks queued but none loaded (paused with no current track): Play
  // starts the queue, so this is a ready state, not "Nothing queued".
  const queueCount = chrome?.queueCount ?? 0;
  const ready = isIdle && queueCount > 0;
  const readyLine = `${queueCount} ${queueCount === 1 ? "track" : "tracks"} queued · press play`;
  // A Mopidy stream with no length is radio: live, counting up, not seekable.
  // External sources (AirPlay etc.) also report len 0 but aren't "LIVE".
  const live = !!track && track.len === 0 && !external;
  const paused = !!track && !playing;
  const len = track && track.len > 0 ? track.len : 0;
  const showTime = !!track && (len > 0 || live);
  const pct = len > 0 ? Math.min(1, Math.max(0, elapsed / len)) : 0;

  const srcName = titleCase(source);
  const title = track ? track.title : ready ? "Ready to play" : isIdle ? "Nothing queued" : isAux ? "Line-in" : srcName;
  const artist = track
    ? track.artist
    : ready ? readyLine
    : isIdle ? "Open the Library to choose music"
    : isAux ? "Playing from the AUX jack" : `Playing from ${srcName}`;
  const album = track?.album ?? "";

  const nav = (label: string, action?: () => void) => ({
    type: "button" as const,
    "aria-label": label,
    onClick: action,
    disabled: !action,
  });

  return (
    <div style={{
      width: 1280, height: 800, overflow: "hidden", position: "relative",
      background: C.bg, color: C.ink, fontFamily: C.serif,
    }}>
      <style>{KEYFRAMES}</style>

      {/* The work: cover on a white mat. */}
      <div style={{
        position: "absolute", left: 100, top: 90, width: 460, height: 460, boxSizing: "border-box",
        padding: 28, background: C.panel,
        boxShadow: `0 1px 0 ${C.rule}, 0 18px 30px -18px rgba(60,40,20,.35)`,
      }}>
        <div data-testid="placard-art" style={{
          width: "100%", height: "100%",
          opacity: paused ? 0.4 : 1, filter: paused ? "grayscale(1)" : "none",
        }}>
          {track ? (
            <Artwork key={track.uri} track={track}/>
          ) : (
            <EmptyMat
              label={isIdle ? "Open Library" : isAux ? "AUX in" : srcName}
              sub={ready ? "Ready to play" : isIdle ? "Nothing queued" : "No track data"}
              onClick={isIdle ? chrome?.onOpenLibrary : undefined}
            />
          )}
        </div>
      </div>

      {/* The label card. */}
      <div style={{
        position: "absolute", left: 640, top: 90, width: 540, height: 460, boxSizing: "border-box",
        padding: "40px 44px 24px", background: C.panel, boxShadow: `0 1px 0 ${C.rule}`,
        display: "flex", flexDirection: "column", gap: 12,
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 12, flexShrink: 0,
          fontFamily: C.mono, fontWeight: 500, fontSize: 22, lineHeight: 1, letterSpacing: "0.1em", color: C.ink2,
        }}>
          <span style={{ width: 14, height: 14, borderRadius: "50%", background: srcColor, flexShrink: 0 }}/>
          <span>{source}</span>
          {live && <span style={{ color: C.accent }}>LIVE</span>}
        </div>

        {/* Keyed by track so a new track cross-fades in (one-shot). */}
        <div key={track?.uri ?? `none:${source}`} style={{
          display: "flex", flexDirection: "column", gap: 12, minHeight: 0,
          animation: "placard-fade 240ms ease-out",
        }}>
          <div data-testid="placard-title" style={{
            fontSize: 50, fontWeight: 500, lineHeight: 1.08,
            display: "-webkit-box", WebkitBoxOrient: "vertical",
            // Make room for the Paused line so the timeline never gets pushed.
            WebkitLineClamp: paused ? 2 : 3, overflow: "hidden",
            textWrap: "pretty", overflowWrap: "anywhere",
          } as React.CSSProperties}>{title}</div>
          <div style={{ fontSize: 30, lineHeight: 1.2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", flexShrink: 0 }}>
            {artist}
          </div>
          {album && (
            <div style={{ fontSize: 26, fontStyle: "italic", lineHeight: 1.2, color: C.ink2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", flexShrink: 0 }}>
              {album}
            </div>
          )}
        </div>

        <div style={{ flex: 1 }}/>

        {paused && (
          <div style={{
            fontFamily: C.serif, fontStyle: "italic", fontWeight: 400, fontSize: 34, lineHeight: 1,
            color: C.accent, display: "flex", alignItems: "center", gap: 14, flexShrink: 0,
          }}>
            <span style={{ width: 40, height: 2, background: C.accent }}/>Paused
          </div>
        )}

        <div style={{
          display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 16, alignItems: "center", flexShrink: 0,
          fontFamily: C.mono, fontWeight: 400, fontSize: 22, lineHeight: 1,
          fontVariantNumeric: "tabular-nums", color: C.ink2, opacity: len > 0 ? 1 : 0.35,
        }}>
          <span style={{ minWidth: 64 }}>{showTime ? mmss(elapsed) : ""}</span>
          <div data-testid="placard-seek" aria-disabled={len > 0 ? undefined : true}
            style={{ height: 72, display: "flex", alignItems: "center" }}>
            <SeekableBar value={pct} lengthSec={len} onSeek={onSeek} hitHeight={70} style={{ flex: 1 }}>
              <div style={{ position: "relative", height: 2, background: C.rule }}>
                <div style={{
                  position: "absolute", left: 0, top: 0, height: 2,
                  width: "calc(var(--seek-fraction) * 100%)", background: C.ink,
                }}/>
                <div style={{
                  position: "absolute", top: -7, left: "calc(var(--seek-fraction) * 100%)",
                  width: 16, height: 16, marginLeft: -8, borderRadius: "50%", background: C.ink,
                }}/>
              </div>
            </SeekableBar>
          </div>
          <span style={{ minWidth: 64, textAlign: "right" }}>{len > 0 ? mmss(len) : live ? "LIVE" : ""}</span>
        </div>
      </div>

      {/* Transport row. */}
      <div style={{
        position: "absolute", left: 100, top: 580, width: 1080, height: 112,
        display: "flex", alignItems: "center", gap: 16,
      }}>
        <Pill label="SHUFFLE" on={shuffle} onClick={onToggleShuffle}/>
        <Pill label="REPEAT" on={repeat} onClick={onToggleRepeat}/>
        {volume != null && (
          <div style={{ fontFamily: C.mono, fontSize: 22, lineHeight: 1, color: C.ink2, paddingLeft: 12, fontVariantNumeric: "tabular-nums" }}>
            VOL {Math.round(volume)}
          </div>
        )}
        <div style={{ flex: 1 }}/>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <button type="button" aria-label="Previous" onClick={onPrev} style={{
            ...BTN_RESET, opacity: track ? 1 : 0.35, width: 92, height: 92, borderRadius: "50%", boxSizing: "border-box",
            border: `2px solid ${C.ink}`, display: "flex", alignItems: "center", justifyContent: "center",
          }}><PrevGlyph/></button>
          <button type="button" aria-label={playing ? "Pause" : "Play"} onClick={onToggle} style={{
            ...BTN_RESET, opacity: track || ready ? 1 : 0.35,
            width: 112, height: 112, borderRadius: "50%", background: C.ink,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>{playing ? <PauseGlyph/> : <PlayGlyph/>}</button>
          <button type="button" aria-label="Next" onClick={onNext} style={{
            ...BTN_RESET, opacity: track ? 1 : 0.35, width: 92, height: 92, borderRadius: "50%", boxSizing: "border-box",
            border: `2px solid ${C.ink}`, display: "flex", alignItems: "center", justifyContent: "center",
          }}><NextGlyph/></button>
        </div>
      </div>

      {/* Navigation rail: always visible, ruled off below the transport. */}
      <nav aria-label="Navigation" style={{
        position: "absolute", left: 100, top: 712, width: 1080, height: 72,
        borderTop: `1px solid ${C.rule}`, display: "flex", ...LABEL_FONT,
      }}>
        <button {...nav("Home", chrome?.onGoHome)} style={{ ...BTN_RESET, flex: 1.4, minWidth: 0, display: "flex", alignItems: "center", gap: 12, height: 72 }}>
          <span style={{ width: 14, height: 14, borderRadius: "50%", background: srcColor, flexShrink: 0 }}/>
          <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            HOME{chrome ? ` · ${chrome.sourceLabel}` : ""}
          </span>
        </button>
        <button {...nav("Library", chrome?.onOpenLibrary)} style={{ ...BTN_RESET, flex: 1, display: "flex", alignItems: "center", justifyContent: "center", height: 72 }}>
          <span style={{ padding: "10px 16px", background: isIdle ? C.accent : "transparent", color: isIdle ? "#FFFFFF" : C.ink }}>LIBRARY</span>
        </button>
        <button {...nav("Queue", chrome?.onOpenQueue)} style={{ ...BTN_RESET, flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 10, height: 72 }}>
          QUEUE
          {chrome && <span style={{ color: C.accent, fontVariantNumeric: "tabular-nums" }}>{chrome.queueCount}</span>}
        </button>
        <button {...nav("Skin", chrome?.onOpenSkinPicker)} style={{ ...BTN_RESET, flex: 1.3, minWidth: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 10, height: 72 }}>
          SKIN
          <span style={{ fontFamily: C.serif, fontStyle: "italic", fontWeight: 400, fontSize: 26, letterSpacing: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {chrome?.skinName ?? "Placard"}
          </span>
        </button>
        <button {...nav("Settings", chrome?.onOpenSettings)} style={{ ...BTN_RESET, flex: 1, display: "flex", alignItems: "center", justifyContent: "flex-end", height: 72 }}>
          SETTINGS
        </button>
      </nav>
    </div>
  );
}

/** Nothing to hang: a dashed outline in the frame. In idle it opens the Library. */
function EmptyMat({ label, sub, onClick }: { label: string; sub: string; onClick?: () => void }) {
  const style: React.CSSProperties = {
    width: "100%", height: "100%", border: `2px dashed ${C.rule}`, boxSizing: "border-box",
    display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
    gap: 14, textAlign: "center", background: "transparent", color: C.ink, margin: 0, padding: 0,
  };
  const inner = (
    <>
      <span style={{ fontFamily: C.serif, fontStyle: "italic", fontWeight: 400, fontSize: 40, lineHeight: 1.1 }}>{label}</span>
      <span style={{ fontFamily: C.mono, fontWeight: 400, fontSize: 22, lineHeight: 1, color: C.ink2 }}>{sub}</span>
    </>
  );
  return onClick
    ? <button type="button" onClick={onClick} style={{ ...style, font: "inherit", cursor: "pointer" }}>{inner}</button>
    : <div style={style}>{inner}</div>;
}
