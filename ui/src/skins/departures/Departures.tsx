// DEPARTURES — split-flap departure board; black, bone and signal yellow.
// Source: claude.ai design "Boombox Skins" artboard 1a.
//
// Motion budget (Pi 5, no fan): the only animation is a one-shot flap flip
// (transform/opacity) when a row's value changes while playing — 70 ms per
// tile, staggered 20 ms, ease-in. The progress fill moves only when the
// elapsed prop ticks. Nothing runs while paused or idle.
import React from "react";
import { mmss } from "../../lib/shared";
import { SeekableBar } from "../../lib/SeekableBar";
import { useAlbumArt } from "../../lib/albumArt";
import type { SkinAudioProps, SkinTheme } from "../../lib/skinRegistry";

const C = {
  bg:     "#111214",
  panel:  "#1C1D20",
  seam:   "#050506",
  ink:    "#F2F0E8",
  ink2:   "#A9A79E",
  yellow: "#FFC629",
  red:    "#E8463A",
  rule:   "#2E2F33",
};

const FONT = "'Barlow Condensed', 'Arial Narrow', system-ui, sans-serif";
const MONO = "'JetBrains Mono', ui-monospace, monospace";

export const DEPARTURES_THEME: SkinTheme = {
  bg: C.bg, panel: C.panel, ink: C.ink, ink2: C.ink2,
  accent: C.yellow, accent2: C.red, rule: C.rule,
  font: FONT, mono: MONO,
};

export const DEPARTURES_SWATCH: string[] = [C.bg, C.ink, C.yellow, C.red];

/** Flap background: a panel split by a thin dark hinge at mid-height. */
const flapBg = (pct: number, col: string = C.panel) =>
  `linear-gradient(${col} 0 ${50 - pct}%, ${C.seam} ${50 - pct}% ${50 + pct}%, ${col} ${50 + pct}%)`;

const FLIP_MS = 70;
const FLIP_STAGGER_MS = 20;

const KEYFRAMES = `
@keyframes dep-flap-flip {
  0%   { transform: perspective(900px) rotateX(88deg); opacity: 0.35; }
  100% { transform: none; opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .dep-flip { animation: none !important; }
}
`;

/** Re-renders its children with a one-shot flip whenever `value` changes
 *  while `playing`. Changes while paused/idle swap instantly. The first
 *  render never animates. */
function Flip({ value, playing, index, style, children }: {
  value: string; playing: boolean; index: number;
  style?: React.CSSProperties; children: React.ReactNode;
}) {
  const [prev, setPrev] = React.useState(value);
  const [flip, setFlip] = React.useState({ n: 0, anim: false });
  if (value !== prev) {
    setPrev(value);
    setFlip(f => ({ n: f.n + 1, anim: playing }));
  }
  return (
    <div
      key={flip.n}
      className={flip.anim ? "dep-flip" : undefined}
      style={{
        transformOrigin: "50% 50%",
        animation: flip.anim
          ? `dep-flap-flip ${FLIP_MS}ms ease-in ${index * FLIP_STAGGER_MS}ms both`
          : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

const LABEL: React.CSSProperties = {
  font: `700 22px/1 ${MONO}`, color: C.yellow, letterSpacing: "0.08em",
};

function Row({ label, top, children }: { label: string; top?: boolean; children: React.ReactNode }) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "110px 1fr", gap: 16,
      alignItems: top ? "start" : "center",
    }}>
      <div style={{ ...LABEL, paddingTop: top ? 24 : 0 }}>{label}</div>
      {children}
    </div>
  );
}

const ONE_LINE: React.CSSProperties = {
  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
};

/** Bare button reset; every control sets its own size (all ≥ 72×72). */
const BTN: React.CSSProperties = {
  border: "none", padding: 0, margin: 0, cursor: "pointer",
  fontFamily: FONT, display: "flex", alignItems: "center", justifyContent: "center",
  borderRadius: 6,
};

function PrevIcon() {
  return <svg width="48" height="48" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h2.5v14H6zM20 5v14L9 12z" fill={C.ink}/></svg>;
}
function NextIcon() {
  return <svg width="48" height="48" viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 5H18v14h-2.5zM4 5v14l11-7z" fill={C.ink}/></svg>;
}
function PlayPauseIcon({ playing }: { playing: boolean }) {
  return playing
    ? <svg width="64" height="64" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h4v16H6zM14 4h4v16h-4z" fill={C.bg}/></svg>
    : <svg width="64" height="64" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z" fill={C.bg}/></svg>;
}

/** Cover art (real URL) with the design's split-flap colour tile fallback. */
function Cover({ artist, album, title, artUrl, hue }: {
  artist: string; album: string; title: string; artUrl?: string; hue: number;
}) {
  // Prefer the resolved art on the track; otherwise ask the art lookup.
  const looked = useAlbumArt(artUrl ? null : artist, artUrl ? null : album, artUrl ? null : title);
  const url = artUrl ?? looked;
  const [failed, setFailed] = React.useState<string | null>(null);
  const initial = ((album || title || "?").trim()[0] ?? "?").toUpperCase();
  if (url && failed !== url) {
    return (
      <img
        src={url} alt="" decoding="async" width={280} height={280}
        onError={() => setFailed(url)}
        style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
      />
    );
  }
  const fb = `oklch(0.68 0.13 ${hue})`;
  return (
    <div data-testid="departures-art-fallback" style={{
      width: "100%", height: "100%", background: flapBg(0.4, fb),
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: 200, fontWeight: 700, lineHeight: 1, color: `oklch(0.42 0.1 ${hue})`,
    }}>{initial}</div>
  );
}

export function DeparturesAudio({
  track, state, elapsed, volume, shuffle = false, repeat = false, chrome,
  onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek,
}: SkinAudioProps) {
  const playing = state === "playing";
  const source = chrome?.sourceLabel ?? "";
  const srcColor = chrome?.sourceColor ?? C.ink2;
  const isAux = !track && source === "AUX";
  // "Idle" = nothing loaded and no external source feeding the speakers.
  const isIdle = !track && !isAux && (!chrome || !chrome.sourceLive || source === "IDLE" || source === "LIBRARY");
  const external = !track && !isAux && !isIdle; // e.g. Bluetooth with no metadata
  // Tracks sit in the queue but none is loaded (e.g. paused with no current
  // track): Play starts the queue, so offer it instead of "Nothing queued".
  const queueCount = chrome?.queueCount ?? 0;
  const ready = isIdle && queueCount > 0;
  const readyLine = `${queueCount} ${queueCount === 1 ? "track" : "tracks"} queued · press play`;
  // LIVE marks radio only: a length-less track playing from the library
  // source (our own player). chrome.sourceLive is true for every external
  // source (AirPlay, Spotify, Bluetooth, AUX), which never shows LIVE.
  const live = !!track && track.len === 0 && (!chrome || chrome.sourceLabel === "LIBRARY");
  const len = track?.len ?? 0;
  const paused = !!track && !playing;

  const prettySource = source ? source.charAt(0) + source.slice(1).toLowerCase() : "";
  const title = track ? track.title
    : isAux ? "Line-in" : external ? prettySource : ready ? "Ready to play" : "Nothing queued";
  const artist = track ? track.artist
    : isAux ? "Playing from the AUX jack" : external ? `Playing via ${prettySource}`
    : ready ? readyLine : "Open the Library to choose music";
  const album = track?.album ?? "";

  // Elapsed shows for timed tracks and counts up for radio streams.
  const showElapsed = !!track && (len > 0 || live);
  const timeL = showElapsed ? mmss(elapsed) : "";
  const timeR = len > 0 ? mmss(len) : live ? "LIVE" : "";
  const seekable = len > 0;
  const pct = seekable ? Math.max(0, Math.min(1, elapsed / len)) : 0;

  const stateWord = playing && track ? "PLAYING"
    : paused ? "PAUSED"
    : isAux ? "LINE-IN"
    : external ? (playing || chrome?.sourceLive ? "PLAYING" : "IDLE")
    : "IDLE";
  const statusBg = paused ? C.red : stateWord === "PLAYING" ? C.yellow : C.panel;
  const statusFg = paused || stateWord === "PLAYING" ? C.bg : C.ink2;

  const ctlDisabled = !track;
  const playDisabled = !track && !ready;
  const skinName = (chrome?.skinName ?? "Departures").toUpperCase();

  const toggleStyle = (on: boolean): React.CSSProperties => ({
    ...BTN, width: 150, height: 96, background: on ? C.yellow : C.panel,
    color: on ? C.bg : C.ink2, fontSize: 30, fontWeight: 700, letterSpacing: "0.06em",
  });

  const navBtn = (flex: number, extra?: React.CSSProperties): React.CSSProperties => ({
    ...BTN, flex, minWidth: 0, height: 72, background: C.panel, color: C.ink,
    fontSize: 28, fontWeight: 700, letterSpacing: "0.05em", gap: 12,
    cursor: chrome ? "pointer" : "default", ...extra,
  });

  return (
    <div style={{
      width: 1280, height: 800, overflow: "hidden", position: "relative",
      background: C.bg, color: C.ink, fontFamily: FONT,
    }}>
      <style>{KEYFRAMES}</style>

      {/* Board: TITLE / ARTIST / ALBUM / VIA flaps. */}
      <div style={{ position: "absolute", left: 60, top: 56, width: 840, display: "flex", flexDirection: "column", gap: 10 }}>
        <Row label="TITLE" top>
          <div style={{ height: 164, boxSizing: "border-box", padding: "12px 20px", background: flapBg(0.4), borderRadius: 6, overflow: "hidden" }}>
            <Flip value={title} playing={playing} index={0}>
              <div data-testid="departures-title" style={{
                fontSize: 64, fontWeight: 700, lineHeight: "70px", textTransform: "uppercase",
                display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2,
                overflow: "hidden", overflowWrap: "anywhere",
              }}>{title}</div>
            </Flip>
          </div>
        </Row>
        <Row label="ARTIST">
          <div style={{ height: 72, padding: "0 20px", background: flapBg(0.7), borderRadius: 6, overflow: "hidden", minWidth: 0 }}>
            <Flip value={artist} playing={playing} index={1}>
              <div style={{ fontSize: 40, fontWeight: 600, lineHeight: "72px", textTransform: "uppercase", ...ONE_LINE }}>{artist}</div>
            </Flip>
          </div>
        </Row>
        <Row label="ALBUM">
          <div style={{ height: 64, padding: "0 20px", background: flapBg(0.8), borderRadius: 6, overflow: "hidden", minWidth: 0 }}>
            <Flip value={album} playing={playing} index={2}>
              <div style={{ fontSize: 34, fontWeight: 500, lineHeight: "64px", color: C.ink2, textTransform: "uppercase", ...ONE_LINE }}>{album || " "}</div>
            </Flip>
          </div>
        </Row>
        <Row label="VIA">
          <div style={{ height: 64, padding: "0 20px", background: flapBg(0.8), borderRadius: 6, overflow: "hidden", minWidth: 0 }}>
            <Flip value={`${source}|${live}`} playing={playing} index={3}
              style={{ height: 64, display: "flex", alignItems: "center", gap: 14, fontSize: 34, fontWeight: 700, letterSpacing: "0.04em" }}>
              {source && <span aria-hidden="true" style={{ width: 18, height: 18, borderRadius: "50%", background: srcColor, flexShrink: 0 }}/>}
              {source && <span style={{ color: srcColor, ...ONE_LINE }}>{source}</span>}
              {live && <span style={{ font: `700 22px/1 ${MONO}`, color: C.ink2 }}>LIVE</span>}
            </Flip>
          </div>
        </Row>
      </div>

      {/* Cover art / empty-state tile. */}
      <div style={{ position: "absolute", left: 940, top: 120, width: 280, height: 280, borderRadius: 6, overflow: "hidden", background: C.panel }}>
        {track ? (
          <Cover key={track.uri} artist={track.artist} album={track.album} title={track.title} artUrl={track.artUrl} hue={track.hue}/>
        ) : isIdle && chrome ? (
          <button
            aria-label="Open Library"
            onClick={chrome.onOpenLibrary}
            style={{ ...BTN, width: "100%", height: "100%", background: "transparent", borderRadius: 0,
              fontSize: 40, fontWeight: 700, color: C.yellow, textTransform: "uppercase", lineHeight: 1.1, textAlign: "center" }}
          >Open Library</button>
        ) : (
          <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 40, fontWeight: 700, color: C.yellow, textTransform: "uppercase", lineHeight: 1.1, textAlign: "center" }}>
            {isAux ? "AUX in" : external ? source : "Nothing queued"}
          </div>
        )}
      </div>

      {/* Status flap. */}
      <div
        role="status"
        aria-label={`Status: ${stateWord.toLowerCase()}`}
        style={{ position: "absolute", left: 940, top: 416, width: 280, height: 64, borderRadius: 6, overflow: "hidden",
          background: statusBg, color: statusFg }}
      >
        <Flip value={stateWord} playing={playing} index={4}
          style={{ height: 64, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 40, fontWeight: 700, letterSpacing: "0.06em" }}>
          {stateWord}
        </Flip>
      </div>

      {/* Time + seek. */}
      <div style={{
        position: "absolute", left: 60, top: 492, width: 1160, height: 72,
        display: "grid", gridTemplateColumns: "100px 1fr 100px", gap: 20, alignItems: "center",
        font: `700 26px/1 ${MONO}`, fontVariantNumeric: "tabular-nums", opacity: seekable ? 1 : 0.35,
      }}>
        <span data-testid="departures-elapsed" style={{ whiteSpace: "nowrap" }}>{timeL}</span>
        <div
          role="slider"
          aria-label="Seek"
          aria-valuemin={0}
          aria-valuemax={Math.max(0, Math.round(len))}
          aria-valuenow={Math.round(seekable ? elapsed : 0)}
          aria-disabled={!seekable}
          style={{ height: 72, display: "flex", flexDirection: "column", justifyContent: "center" }}
        >
          <SeekableBar value={pct} lengthSec={len} onSeek={seekable ? onSeek : undefined} hitHeight={58}>
            <div style={{ height: 14, background: C.rule, borderRadius: 2, overflow: "hidden" }}>
              <div style={{
                height: "100%", width: "100%", background: C.yellow, transformOrigin: "0 50%",
                transform: "scaleX(var(--seek-fraction, 0))",
              }}/>
            </div>
          </SeekableBar>
        </div>
        <span style={{ textAlign: "right", color: C.ink2, whiteSpace: "nowrap" }}>{timeR}</span>
      </div>

      {/* Transport row. */}
      <div style={{ position: "absolute", left: 60, top: 582, width: 1160, height: 112, display: "flex", alignItems: "center", gap: 12 }}>
        <button aria-label="Shuffle" aria-pressed={shuffle} onClick={onToggleShuffle} style={toggleStyle(shuffle)}>SHUFFLE</button>
        <button aria-label="Repeat" aria-pressed={repeat} onClick={onToggleRepeat} style={toggleStyle(repeat)}>REPEAT</button>
        {volume != null && (
          <div aria-label={`Volume ${volume}`} style={{
            width: 150, height: 96, borderRadius: 6, background: C.panel, display: "flex", alignItems: "center",
            justifyContent: "center", font: `700 26px/1 ${MONO}`, color: C.ink2, fontVariantNumeric: "tabular-nums",
          }}>VOL {Math.round(volume)}</div>
        )}
        <div style={{ flex: 1 }}/>
        <div style={{ display: "flex", gap: 12 }}>
          <button aria-label="Previous" disabled={ctlDisabled} onClick={onPrev}
            style={{ ...BTN, width: 112, height: 112, background: C.panel, opacity: ctlDisabled ? 0.35 : 1, cursor: ctlDisabled ? "default" : "pointer" }}><PrevIcon/></button>
          <button aria-label={playing ? "Pause" : "Play"} disabled={playDisabled} onClick={onToggle}
            style={{ ...BTN, width: 180, height: 112, background: C.yellow, opacity: playDisabled ? 0.35 : 1, cursor: playDisabled ? "default" : "pointer" }}>
            <PlayPauseIcon playing={playing && !!track}/>
          </button>
          <button aria-label="Next" disabled={ctlDisabled} onClick={onNext}
            style={{ ...BTN, width: 112, height: 112, background: C.panel, opacity: ctlDisabled ? 0.35 : 1, cursor: ctlDisabled ? "default" : "pointer" }}><NextIcon/></button>
        </div>
      </div>

      {/* Navigation: always visible. */}
      <nav aria-label="Main menu" style={{ position: "absolute", left: 60, top: 712, width: 1160, height: 72, display: "flex", gap: 10 }}>
        <button aria-label="Home" disabled={!chrome} onClick={chrome?.onGoHome} style={navBtn(1.3)}>
          {source && <span aria-hidden="true" style={{ width: 16, height: 16, borderRadius: "50%", background: srcColor, flexShrink: 0 }}/>}
          <span style={ONE_LINE}>{source ? `HOME · ${source}` : "HOME"}</span>
        </button>
        <button aria-label="Library" disabled={!chrome} onClick={chrome?.onOpenLibrary}
          style={navBtn(1, isIdle ? { background: C.yellow, color: C.bg } : undefined)}>LIBRARY</button>
        <button aria-label={chrome ? `Queue, ${queueCount}` : "Queue"} disabled={!chrome} onClick={chrome?.onOpenQueue} style={navBtn(1)}>
          QUEUE
          {chrome && <span style={{ font: `700 24px/1 ${MONO}`, color: C.yellow, fontVariantNumeric: "tabular-nums" }}>{queueCount}</span>}
        </button>
        <button aria-label={`Skin: ${chrome?.skinName ?? "Departures"}`} disabled={!chrome} onClick={chrome?.onOpenSkinPicker} style={navBtn(1.3, { gap: 10 })}>
          SKIN <span style={{ color: C.ink2, ...ONE_LINE }}>{skinName}</span>
        </button>
        <button aria-label="Settings" disabled={!chrome} onClick={chrome?.onOpenSettings} style={navBtn(1)}>SETTINGS</button>
      </nav>
    </div>
  );
}
