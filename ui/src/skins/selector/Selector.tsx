// SELECTOR — jukebox title strip, 45 rpm label and push buttons.
// Cream paper, oxblood ink, red/teal accents. The record does not spin: the
// only motion is a one-shot strip slide on track change, a one-shot PAUSED
// stamp, and the push buttons sinking 8 px while pressed (transform only).
import React from "react";
import { mmss } from "../../lib/shared";
import { SeekableBar } from "../../lib/SeekableBar";
import { useAlbumArt } from "../../lib/albumArt";
import type { SkinAudioProps, SkinTheme } from "../../lib/skinRegistry";
import type { Track } from "../../lib/types";

const C = {
  bg:     "#F3E9D2",
  panel:  "#FFF8E8",
  ink:    "#2A1A14",
  ink2:   "#6B4E3D",
  red:    "#C8352B",
  teal:   "#1F6B7A",
  idle:   "#8A8A8A",
  vinyl:  "#1C1412",
  groove: "#271c19",
};
const SLAB = "'Zilla Slab', Rockwell, 'Roboto Slab', Georgia, serif";
const COURIER = "'Courier Prime', 'Courier New', ui-monospace, monospace";

export const SELECTOR_THEME: SkinTheme = {
  bg: C.bg, panel: C.panel, ink: C.ink, ink2: C.ink2,
  accent: C.red, accent2: C.teal,
  rule: C.ink,
  font: SLAB, mono: COURIER,
};

export const SELECTOR_SWATCH: string[] = [C.bg, C.ink, C.red, C.teal];

// Scoped CSS: the press "sink" needs :active, and the one-shot keyframes.
// Everything animates transform/opacity only.
const CSS = `
.sel-key{transition:transform 90ms ease-out;box-shadow:0 8px 0 ${C.ink};}
.sel-key:active:not(:disabled){transform:translateY(8px);box-shadow:none;}
.sel-key:disabled{cursor:default;}
.sel-nav{transition:transform 90ms ease-out;}
.sel-nav:active:not(:disabled){transform:translateY(3px);}
.sel-key:focus-visible,.sel-nav:focus-visible{outline:3px solid ${C.teal};outline-offset:4px;}
@keyframes sel-strip-in{from{transform:translateX(64px);opacity:0}to{transform:none;opacity:1}}
.sel-strip-in{animation:sel-strip-in 360ms cubic-bezier(.2,.8,.2,1) both;}
@keyframes sel-stamp{from{transform:rotate(-6deg) scale(1.35);opacity:0}to{transform:rotate(-6deg) scale(1);opacity:1}}
.sel-stamp{animation:sel-stamp 160ms ease-out both;}
@media (prefers-reduced-motion:reduce){.sel-strip-in,.sel-stamp{animation:none}}
`;

function Label45({ track }: { track: Track | null }) {
  // artUrl first, then the shared /api/art lookup, then the plain 45 label.
  const [failed, setFailed] = React.useState<string[]>([]);
  const own = track?.artUrl && !failed.includes(track.artUrl) ? track.artUrl : null;
  const looked = useAlbumArt(
    own || !track ? null : track.artist,
    own || !track ? null : track.album,
    own || !track ? null : track.title,
  );
  const art = own ?? (looked && !failed.includes(looked) ? looked : null);
  const initial = ((track?.album || track?.title || "?").trim()[0] ?? "?").toUpperCase();
  let face: React.ReactNode;
  if (!track) {
    face = <div style={{ width: "100%", height: "100%", background: C.red }} />;
  } else if (art) {
    face = (
      <img src={art} alt="" decoding="async" onError={() => setFailed(f => [...f, art])}
        style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
    );
  } else {
    face = (
      <div data-testid="selector-fallback-label" style={{
        width: "100%", height: "100%", background: `oklch(0.68 0.13 ${track.hue})`,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        font: `700 64px/1 ${SLAB}`, color: C.panel,
      }}>
        <span style={{ width: "100%", height: 3, background: C.panel, opacity: 0.6, marginBottom: 6 }} />
        {initial}
      </div>
    );
  }
  return (
    <div aria-hidden="true" style={{
      position: "absolute", left: 70, top: 110, width: 300, height: 300, borderRadius: "50%",
      background: `repeating-radial-gradient(circle, ${C.vinyl} 0 3px, ${C.groove} 3px 5px)`,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{ width: 170, height: 170, borderRadius: "50%", overflow: "hidden", position: "relative" }}>
        {face}
        <div style={{ position: "absolute", left: 79, top: 79, width: 12, height: 12, borderRadius: "50%", background: C.bg }} />
      </div>
    </div>
  );
}

const ICONS = {
  prev:  "M6 5h2.5v14H6zM20 5v14L9 12z",
  next:  "M15.5 5H18v14h-2.5zM4 5v14l11-7z",
  pause: "M6 4h4v16H6zM14 4h4v16h-4z",
  play:  "M7 4l13 8-13 8z",
};
function Glyph({ d, size, fill }: { d: string; size: number; fill: string }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"><path d={d} fill={fill} /></svg>;
}

type KeyProps = {
  label: string; w: number; h: number; bg: string; fg: string;
  onClick?: () => void; disabled?: boolean; dim?: boolean; pressed?: boolean; children: React.ReactNode;
};
function Key({ label, w, h, bg, fg, onClick, disabled, dim, pressed, children }: KeyProps) {
  return (
    <button type="button" className="sel-key" aria-label={label} aria-pressed={pressed}
      onClick={onClick} disabled={disabled || !onClick}
      style={{
        width: w, height: h, boxSizing: "border-box", border: `3px solid ${C.ink}`, borderRadius: 12,
        background: bg, color: fg, padding: 0, margin: 0, cursor: "pointer",
        display: "flex", alignItems: "center", justifyContent: "center",
        font: `700 26px/1 ${SLAB}`, letterSpacing: "0.06em",
        opacity: dim ? 0.35 : 1, flexShrink: 0,
      }}>
      {children}
    </button>
  );
}

function NavKey({ label, flex, bg = C.panel, fg = C.ink, onClick, children }: {
  label: string; flex: number; bg?: string; fg?: string; onClick?: () => void; children: React.ReactNode;
}) {
  return (
    <button type="button" className="sel-nav" aria-label={label} onClick={onClick} disabled={!onClick}
      style={{
        flex, minWidth: 0, height: 72, boxSizing: "border-box",
        border: `3px solid ${C.ink}`, borderRadius: 10, background: bg, color: fg,
        display: "flex", alignItems: "center", justifyContent: "center", gap: 10, padding: "0 6px",
        font: `700 24px/1 ${COURIER}`, cursor: onClick ? "pointer" : "default", whiteSpace: "nowrap",
        overflow: "hidden",
      }}>
      {children}
    </button>
  );
}

const ellipsis: React.CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 };

export function SelectorAudio({
  track, state, elapsed, volume, shuffle = false, repeat = false, chrome,
  onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek,
}: SkinAudioProps) {
  const playing = state === "playing";
  const paused = !!track && !playing;
  const isAux = !track && chrome?.sourceLabel === "AUX";
  const idle = !track && !isAux;
  // Tracks queued but none loaded (paused with no current track): Play
  // starts the queue, so this is a ready state, not "Nothing queued".
  const queueCount = chrome?.queueCount ?? 0;
  const ready = idle && !chrome?.sourceLive && queueCount > 0;
  const readyLine = `${queueCount} ${queueCount === 1 ? "track" : "tracks"} queued · press play`;
  const len = track && track.len > 0 ? track.len : 0;
  // Radio = a library (Mopidy) stream with no length. Only radio is LIVE;
  // external sources (AirPlay, Spotify, Bluetooth, AUX) have no meaningful
  // position, so they show neither times nor a LIVE tag.
  const radio = !!track && len === 0 && (!chrome || chrome.sourceLabel === "LIBRARY");
  const live = radio && playing;
  const showTime = !!track && (len > 0 || radio);
  const el = Math.max(0, elapsed);
  const pct = len ? Math.min(1, el / len) : 0;
  const seekable = len > 0 && !!onSeek;

  const title = track ? track.title : ready ? "Ready to play" : idle ? "Nothing queued" : "Line-in";
  const artist = track ? track.artist
    : ready ? readyLine : idle ? "Open the Library to choose music" : "Playing from the AUX jack";
  const album = track?.album ?? "";
  const srcColor = chrome?.sourceColor ?? C.idle;

  // One-shot slide-in when the track changes (not on first mount).
  const key = track?.uri ?? (isAux ? "aux" : "idle");
  const [strip, setStrip] = React.useState({ key, changed: false });
  if (strip.key !== key) setStrip({ key, changed: true });
  const animateStrip = strip.changed || strip.key !== key;

  return (
    <div data-skin="selector" style={{
      width: 1280, height: 800, overflow: "hidden", position: "relative",
      background: C.bg, color: C.ink, fontFamily: SLAB,
    }}>
      <style>{CSS}</style>

      <Label45 key={track?.uri ?? "none"} track={track} />

      {/* Source + volume under the record */}
      <div style={{
        position: "absolute", left: 70, top: 436, width: 300, display: "flex", flexDirection: "column",
        alignItems: "center", gap: 8, font: `700 26px/1 ${COURIER}`,
      }}>
        {chrome && (
          <div data-testid="selector-source" style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ width: 20, height: 20, boxSizing: "border-box", borderRadius: "50%", background: srcColor, border: `2px solid ${C.ink}` }} />
            {chrome.sourceLabel}
            {live && <span style={{ color: C.red }}>LIVE</span>}
          </div>
        )}
        {!chrome && live && <div style={{ color: C.red }}>LIVE</div>}
        {volume != null && (
          <div style={{ fontWeight: 400, fontSize: 24, color: C.ink2, fontVariantNumeric: "tabular-nums" }}>
            VOL {Math.round(volume)}
          </div>
        )}
      </div>

      {/* Title strip */}
      <div data-testid="selector-strip" style={{
        position: "absolute", left: 420, top: 110, width: 790, height: 300, boxSizing: "border-box",
        border: `3px solid ${C.ink}`, background: C.panel,
      }}>
        <div key={key} className={animateStrip ? "sel-strip-in" : undefined}
          style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ flex: 1, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: "0 32px", textAlign: "center" }}>
            <div data-testid="selector-title" style={{
              fontSize: 48, fontWeight: 700, lineHeight: 1.08, textTransform: "uppercase",
              display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2, overflow: "hidden",
              textWrap: "balance", overflowWrap: "anywhere",
            } as React.CSSProperties}>{title}</div>
          </div>
          <div style={{
            height: 72, flexShrink: 0, background: paused ? C.ink2 : C.red, color: C.panel,
            display: "flex", alignItems: "center", justifyContent: "center", padding: "0 32px",
            fontSize: 34, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase",
          }}>
            <span data-testid="selector-artist" style={ellipsis}>{artist}</span>
          </div>
          <div style={{
            height: 64, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
            padding: "0 32px", font: `italic 400 26px/1 ${COURIER}`, color: C.ink2,
          }}>
            <span style={ellipsis}>{album}</span>
          </div>
        </div>
        {paused && (
          <div className="sel-stamp" aria-hidden="true" style={{
            position: "absolute", right: 28, top: -26, transform: "rotate(-6deg)",
            border: `4px solid ${C.red}`, color: C.red, background: C.panel, padding: "6px 18px",
            fontSize: 44, fontWeight: 700, letterSpacing: "0.12em", lineHeight: 1.2,
          }}>PAUSED</div>
        )}
      </div>

      {/* Time + seek */}
      <div style={{
        position: "absolute", left: 420, top: 432, width: 790, height: 72,
        display: "grid", gridTemplateColumns: "84px 1fr 84px", gap: 16, alignItems: "center",
        font: `700 24px/1 ${COURIER}`, fontVariantNumeric: "tabular-nums",
        opacity: len ? 1 : 0.35,
      }}>
        <span data-testid="selector-elapsed" style={{ whiteSpace: "nowrap" }}>{showTime ? mmss(el) : ""}</span>
        <div role="slider" aria-label="Seek" aria-valuemin={0} aria-valuemax={len}
          aria-valuenow={Math.round(len ? Math.min(el, len) : 0)} aria-disabled={!seekable}
          aria-valuetext={len ? `${mmss(el)} of ${mmss(len)}` : live ? "Live" : "Not seekable"}>
          <SeekableBar value={pct} lengthSec={len} onSeek={seekable ? onSeek : undefined} hitHeight={50}>
            <div style={{
              width: "100%", height: 22, boxSizing: "border-box", border: `3px solid ${C.ink}`, borderRadius: 11,
              overflow: "hidden", background: C.panel,
            }}>
              <div style={{
                height: "100%", width: "100%", background: C.red, transformOrigin: "left center",
                transform: "scaleX(var(--seek-fraction))",
              }} />
            </div>
          </SeekableBar>
        </div>
        <span style={{ textAlign: "right", color: C.ink2, whiteSpace: "nowrap" }}>
          {len ? mmss(len) : live ? "LIVE" : ""}
        </span>
      </div>

      {/* Push buttons */}
      <div style={{
        position: "absolute", left: 70, top: 540, width: 1140, height: 144,
        display: "flex", alignItems: "flex-start", justifyContent: "center", gap: 16,
      }}>
        <Key label="Shuffle" w={156} h={126} pressed={shuffle} onClick={onToggleShuffle}
          bg={shuffle ? C.teal : C.panel} fg={shuffle ? C.panel : C.ink}>SHUFFLE</Key>
        <Key label="Previous" w={156} h={126} bg={C.panel} fg={C.ink} onClick={onPrev}
          disabled={!track} dim={!track}><Glyph d={ICONS.prev} size={48} fill={C.ink} /></Key>
        <Key label={playing ? "Pause" : "Play"} w={266} h={134} bg={C.red} fg={C.panel} onClick={onToggle}
          disabled={!track && !ready} dim={!track && !ready}>
          <Glyph d={playing ? ICONS.pause : ICONS.play} size={72} fill={C.panel} />
        </Key>
        <Key label="Next" w={156} h={126} bg={C.panel} fg={C.ink} onClick={onNext}
          disabled={!track} dim={!track}><Glyph d={ICONS.next} size={48} fill={C.ink} /></Key>
        <Key label="Repeat" w={156} h={126} pressed={repeat} onClick={onToggleRepeat}
          bg={repeat ? C.teal : C.panel} fg={repeat ? C.panel : C.ink}>REPEAT</Key>
      </div>

      {/* Navigation row */}
      <nav aria-label="Main menu" style={{
        position: "absolute", left: 70, top: 708, width: 1140, height: 72, display: "flex", gap: 12,
      }}>
        <NavKey label="Home" flex={1.3} onClick={chrome?.onGoHome}>
          <span style={{ width: 18, height: 18, flexShrink: 0, boxSizing: "border-box", borderRadius: "50%", background: srcColor, border: `2px solid ${C.ink}` }} />
          <span style={ellipsis}>HOME{chrome ? ` · ${chrome.sourceLabel}` : ""}</span>
        </NavKey>
        <NavKey label="Library" flex={1} onClick={chrome?.onOpenLibrary}
          bg={idle ? C.red : C.panel} fg={idle ? C.panel : C.ink}>LIBRARY</NavKey>
        <NavKey label="Queue" flex={1} onClick={chrome?.onOpenQueue}>
          QUEUE
          {chrome && <span style={{ color: C.red, fontVariantNumeric: "tabular-nums" }}>{chrome.queueCount}</span>}
        </NavKey>
        <NavKey label="Skin" flex={1.2} onClick={chrome?.onOpenSkinPicker}>
          SKIN
          {chrome && <span style={{ ...ellipsis, color: C.ink2, textTransform: "uppercase" }}>{chrome.skinName}</span>}
        </NavKey>
        <NavKey label="Settings" flex={1} onClick={chrome?.onOpenSettings}>SETTINGS</NavKey>
      </nav>
    </div>
  );
}
