// POSTER — Swiss concert poster; giant type on a red column.
// Design: "Boombox Skins" canvas, artboard 1c. A 400 px red nav/transport
// column on the left; the right side is a cream poster with the title set
// huge in condensed Archivo. Paused turns the column black (200 ms
// opacity cross-fade). A new title slides up 24 px and fades in once
// (320 ms, transform/opacity). Nothing loops.
import React from "react";
import { mmss } from "../../lib/shared";
import { SeekableBar } from "../../lib/SeekableBar";
import { useAlbumArt } from "../../lib/albumArt";
import type { SkinAudioProps, SkinTheme } from "../../lib/skinRegistry";

const P = {
  bg:     "#F1EEE6",
  red:    "#E33B24",
  black:  "#121212",
  ink:    "#121212",
  ink2:   "#4A4741",
  blue:   "#1F4FD1",
  rule:   "#D9D4C8",
  white:  "#FFFFFF",
  font:   "'Archivo Variable', 'Archivo', 'Helvetica Neue', Arial, system-ui, sans-serif",
  mono:   "'DM Mono', 'JetBrains Mono', ui-monospace, monospace",
};

export const POSTER_THEME: SkinTheme = {
  bg: P.bg, panel: P.red, ink: P.ink, ink2: P.ink2,
  accent: P.red, accent2: P.blue,
  rule: P.rule,
  font: P.font, mono: P.mono,
};

export const POSTER_SWATCH: string[] = [P.bg, P.red, P.black, P.blue];

const EASE_OUT = "cubic-bezier(0.215, 0.61, 0.355, 1)";
const NAV_RULE = "2px solid rgba(255,255,255,.5)";

// One-shot keyframes for the title entrance (transform/opacity only).
const KEYFRAMES = `@keyframes poster-title-in{from{opacity:0;transform:translateY(24px)}to{opacity:1;transform:none}}`;

const resetBtn: React.CSSProperties = {
  appearance: "none", border: "none", background: "transparent", padding: 0, margin: 0,
  font: "inherit", color: "inherit", textAlign: "left", cursor: "pointer",
};

function PrevGlyph() {
  return <svg width="44" height="44" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h2.5v14H6zM20 5v14L9 12z" fill={P.white}/></svg>;
}
function NextGlyph() {
  return <svg width="44" height="44" viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 5H18v14h-2.5zM4 5v14l11-7z" fill={P.white}/></svg>;
}
function PauseGlyph() {
  return <svg width="72" height="72" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h4v16H6zM14 4h4v16h-4z" fill={P.black}/></svg>;
}
function PlayGlyph() {
  return <svg width="72" height="72" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z" fill={P.black}/></svg>;
}

type NavRowProps = {
  label: string;
  onClick?: () => void;
  last?: boolean;
  children: React.ReactNode;
  justify?: React.CSSProperties["justifyContent"];
};

function NavRow({ label, onClick, last, children, justify = "space-between" }: NavRowProps) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={!onClick}
      style={{
        ...resetBtn,
        width: "100%", height: 76, boxSizing: "content-box", display: "flex", alignItems: "center", justifyContent: justify,
        gap: 14, fontSize: 30, fontWeight: 700, color: P.white,
        borderBottom: last ? "none" : NAV_RULE,
        cursor: onClick ? "pointer" : "default",
      }}
    >
      {children}
    </button>
  );
}

function ToggleBtn({ label, on, onClick }: { label: string; on: boolean; onClick?: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={on}
      onClick={onClick}
      style={{
        ...resetBtn,
        flex: 1, height: 72, boxSizing: "content-box", border: `3px solid ${P.white}`,
        background: on ? P.white : "transparent", color: on ? P.black : P.white,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 24, fontWeight: 700,
      }}
    >
      {label}
    </button>
  );
}

/** Album art, or the design's two-tone block with a heavy initial when the
 *  track has no art (or the image fails to load). */
function PosterArt({ url, hue, initial }: { url?: string; hue: number; initial: string }) {
  const [failedUrl, setFailedUrl] = React.useState<string | null>(null);
  const showImg = !!url && failedUrl !== url;
  if (showImg) {
    return (
      <div style={{ width: "100%", height: "100%",
        background: "repeating-linear-gradient(135deg,#dcd7cb 0 10px,#d2cdc1 10px 20px)" }}>
        <img
          src={url}
          alt=""
          decoding="async"
          width={260}
          height={260}
          onError={() => setFailedUrl(url ?? null)}
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
        />
      </div>
    );
  }
  return (
    <div data-testid="poster-art-fallback"
      style={{ width: "100%", height: "100%", background: `oklch(0.68 0.13 ${hue})`, position: "relative" }}>
      <div style={{ position: "absolute", right: 0, bottom: 0, width: "50%", height: "50%",
        background: `oklch(0.42 0.1 ${hue})` }}/>
      <div aria-hidden="true" style={{ position: "absolute", left: 20, top: 10, fontSize: 150, fontWeight: 900,
        color: P.bg, lineHeight: 1 }}>{initial}</div>
    </div>
  );
}

export function PosterAudio({
  track, state, elapsed, volume, shuffle = false, repeat = false, chrome,
  onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek,
}: SkinAudioProps) {
  const playing = state === "playing";
  const hasTrack = !!track;
  const paused = hasTrack && !playing;
  const isAux = !track && chrome?.sourceLabel === "AUX";
  const idle = !track && !isAux;
  // LIVE lights only for radio: a length-less track playing through the
  // library (Mopidy). chrome.sourceLive is true for every external source
  // (AirPlay, Spotify, Bluetooth, AUX), which the design never tags LIVE.
  const fromLibrary = !chrome || chrome.sourceLabel === "LIBRARY";
  const live = !!track && track.len === 0 && playing && fromLibrary;

  const len = track && track.len > 0 ? track.len : 0;
  const seekable = len > 0;
  const pct = seekable ? Math.min(1, Math.max(0, elapsed / len)) : 0;
  const showTime = hasTrack && (seekable || live);

  const title = track ? track.title : idle ? "Nothing queued" : "Line-in";
  const artist = track ? track.artist : idle ? "Open the Library to choose music" : "Playing from the AUX jack";
  const album = track?.album ?? "";
  const initial = ((track?.album || track?.title || "?").trim()[0] ?? "?").toUpperCase();
  const ctlOp = hasTrack ? 1 : 0.35;

  // Art: track.artUrl, else the shared /api/art lookup (skipped for radio
  // streams, whose "artist" is a station name), else the two-tone block.
  const isRadio = !!track && track.len === 0 && fromLibrary;
  const lookup = !!track && !track.artUrl && !isRadio;
  const lookedUp = useAlbumArt(
    lookup ? track.artist : null,
    lookup ? track.album || null : null,
    lookup ? track.title : null,
  );
  const artUrl = track?.artUrl || (lookup ? lookedUp : null) || undefined;

  return (
    <div style={{
      width: 1280, height: 800, overflow: "hidden", position: "relative",
      background: P.bg, color: P.ink, fontFamily: P.font,
    }}>
      <style>{KEYFRAMES}</style>

      {/* ── Red column: nav + toggles + transport ───────────────────── */}
      <div style={{ position: "absolute", left: 0, top: 0, width: 400, height: 800, background: P.red, color: P.white }}>
        {/* Paused: black layer cross-fades over the red (opacity only). */}
        <div aria-hidden="true" data-testid="poster-pause-layer" style={{
          position: "absolute", inset: 0, background: P.black,
          opacity: paused ? 1 : 0, transition: "opacity 200ms linear",
        }}/>

        <nav aria-label="Main menu" style={{ position: "absolute", left: 24, top: 28, width: 352,
          display: "flex", flexDirection: "column" }}>
          <NavRow label="Home" onClick={chrome?.onGoHome} justify="flex-start">
            {chrome && (
              <span aria-hidden="true" style={{ width: 18, height: 18, borderRadius: "50%", flexShrink: 0,
                background: chrome.sourceColor, boxShadow: `0 0 0 3px ${P.white}` }}/>
            )}
            Home
          </NavRow>
          <NavRow label="Library" onClick={chrome?.onOpenLibrary}>
            <span style={{ background: idle ? P.white : "transparent", color: idle ? P.red : P.white,
              padding: "4px 8px", marginLeft: -8 }}>Library</span>
          </NavRow>
          <NavRow label={chrome ? `Queue, ${chrome.queueCount}` : "Queue"} onClick={chrome?.onOpenQueue}>
            Queue
            {chrome && (
              <span style={{ font: `500 26px/1 ${P.mono}`, fontVariantNumeric: "tabular-nums" }}>
                {chrome.queueCount}
              </span>
            )}
          </NavRow>
          <NavRow label={chrome ? `Skin, ${chrome.skinName}` : "Skin"} onClick={chrome?.onOpenSkinPicker}>
            Skin
            <span style={{ fontSize: 24, fontWeight: 500, minWidth: 0, overflow: "hidden",
              textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{chrome?.skinName ?? "Poster"}</span>
          </NavRow>
          <NavRow label="Settings" onClick={chrome?.onOpenSettings} last justify="flex-start">
            Settings
          </NavRow>
        </nav>

        <div style={{ position: "absolute", left: 24, top: 448, width: 352, display: "flex", gap: 16 }}>
          <ToggleBtn label="Shuffle" on={shuffle} onClick={onToggleShuffle}/>
          <ToggleBtn label="Repeat" on={repeat} onClick={onToggleRepeat}/>
        </div>

        <div style={{ position: "absolute", left: 24, top: 576, width: 352, height: 180,
          display: "flex", alignItems: "center", gap: 8, opacity: ctlOp }}>
          <button type="button" aria-label="Previous" onClick={onPrev} style={{ ...resetBtn,
            width: 88, height: 160, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <PrevGlyph/>
          </button>
          <button type="button" aria-label={playing ? "Pause" : "Play"} onClick={onToggle} style={{ ...resetBtn,
            width: 160, height: 160, background: P.white,
            display: "flex", alignItems: "center", justifyContent: "center" }}>
            {playing ? <PauseGlyph/> : <PlayGlyph/>}
          </button>
          <button type="button" aria-label="Next" onClick={onNext} style={{ ...resetBtn,
            width: 88, height: 160, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <NextGlyph/>
          </button>
        </div>
      </div>

      {/* ── Poster side ─────────────────────────────────────────────── */}
      <div style={{ position: "absolute", left: 460, top: 140, width: 760, display: "flex", alignItems: "center",
        gap: 14, fontSize: 24, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase" }}>
        {chrome && (
          <>
            <span aria-hidden="true" style={{ width: 16, height: 16, borderRadius: "50%", flexShrink: 0,
              background: chrome.sourceColor }}/>
            <span>{chrome.sourceLabel}</span>
          </>
        )}
        {live && <span style={{ color: P.red }}>Live</span>}
        {paused && (
          <span style={{ background: P.black, color: P.bg, padding: "6px 12px", letterSpacing: ".1em" }}>Paused</span>
        )}
        <span style={{ flex: 1 }}/>
        {volume != null && (
          <span style={{ font: `500 24px/1 ${P.mono}`, color: P.ink2, fontVariantNumeric: "tabular-nums",
            whiteSpace: "nowrap" }}>
            {`VOL ${Math.round(volume)}`}
          </span>
        )}
      </div>

      <div
        key={`${track?.uri ?? ""}|${title}`}
        data-testid="poster-title"
        style={{
          position: "absolute", left: 460, top: 190, width: 760,
          fontSize: 86, fontWeight: 800, fontStretch: "88%", lineHeight: 0.96, letterSpacing: "-.02em",
          display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 3, overflow: "hidden",
          textWrap: "balance", overflowWrap: "anywhere",
          animation: `poster-title-in 320ms ${EASE_OUT} both`,
        } as React.CSSProperties}
      >
        {title}
      </div>

      <div style={{ position: "absolute", left: 460, top: 500, width: 460, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 36, fontWeight: 700, lineHeight: 1.1, whiteSpace: "nowrap", overflow: "hidden",
          textOverflow: "ellipsis" }}>{artist}</div>
        {album && (
          <div style={{ fontSize: 26, color: P.ink2, whiteSpace: "nowrap", overflow: "hidden",
            textOverflow: "ellipsis" }}>{album}</div>
        )}
      </div>

      {/* Seek: 10 px bar with a 72 px touch band. Disabled for live / unknown length. */}
      <div
        role="slider"
        aria-label="Seek"
        aria-disabled={!seekable}
        aria-valuemin={0}
        aria-valuemax={len}
        aria-valuenow={Math.floor(seekable ? Math.min(elapsed, len) : 0)}
        aria-valuetext={showTime ? mmss(elapsed) : undefined}
        style={{ position: "absolute", left: 460, top: 706, width: 460, opacity: seekable ? 1 : 0.35 }}
      >
        <SeekableBar value={pct} lengthSec={len} onSeek={seekable ? onSeek : undefined} hitHeight={72}>
          <div style={{ height: 10, background: P.rule, position: "relative", overflow: "hidden" }}>
            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: "100%", background: P.black,
              transformOrigin: "left center", transform: "scaleX(var(--seek-fraction))" }}/>
          </div>
        </SeekableBar>
        <div style={{ display: "flex", justifyContent: "space-between", paddingTop: 12,
          font: `500 24px/1 ${P.mono}`, fontVariantNumeric: "tabular-nums", minHeight: 24 }}>
          <span>{showTime ? mmss(elapsed) : ""}</span>
          <span style={{ color: P.ink2 }}>{seekable ? mmss(len) : showTime ? "LIVE" : ""}</span>
        </div>
      </div>

      <div style={{ position: "absolute", left: 960, top: 500, width: 260, height: 260, overflow: "hidden" }}>
        {track ? (
          <PosterArt key={track.uri} url={artUrl} hue={track.hue} initial={initial}/>
        ) : idle ? (
          <button type="button" aria-label="Open Library" onClick={chrome?.onOpenLibrary} disabled={!chrome}
            style={{ ...resetBtn, width: "100%", height: "100%", boxSizing: "border-box",
              border: `3px solid ${P.black}`, padding: 20, display: "flex", alignItems: "flex-end",
              fontSize: 36, fontWeight: 800, lineHeight: 1, color: P.ink,
              cursor: chrome ? "pointer" : "default" }}>
            Open Library
          </button>
        ) : (
          <div style={{ width: "100%", height: "100%", boxSizing: "border-box", border: `3px solid ${P.black}`,
            padding: 20, display: "flex", alignItems: "flex-end", fontSize: 36, fontWeight: 800, lineHeight: 1 }}>
            AUX in
          </div>
        )}
      </div>
    </div>
  );
}
