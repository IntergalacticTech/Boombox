// DECK//OS — terminal/cyberpunk tape-deck terminal
// Adapted from skins/deckos/source.jsx by the designer.
// Diff vs. source: window globals (TRACKS/SOURCES/Icon/useTicker/vu/mmss) replaced
// by ES imports; props consume live Mopidy state; Object.assign(window,…) export
// replaced by ES exports. Visual code is otherwise unchanged.

import React from "react";
import { useTicker, vu, mmss, SOURCES } from "../../lib/shared";
import { useSpectrum } from "../../lib/spectrum";
import { ChromeSourceBtn, ChromeQueueBtn, ChromeSkinBtn, ChromeSettingsBtn } from "../../lib/ChromeButtons";
import { SeekableBar } from "../../lib/SeekableBar";
import { AlbumThumb } from "../../lib/AlbumThumb";
import type { ChromeApi } from "../../lib/skinRegistry";
import type { Track, PlayState } from "../../lib/types";

const DECK = {
  bg:       "#0a0e0c",
  panel:    "#0f1614",
  panelHi:  "#152120",
  ink:      "#9bf2c0",   // phosphor green
  ink2:     "#5da78a",
  dim:      "#2c4a3f",
  mag:      "#ff4fa8",
  cyan:     "#5be9ff",
  amber:    "#ffb84d",
  red:      "#ff5566",
  rule:     "rgba(155,242,192,0.18)",
  font:     "'JetBrains Mono', 'Space Mono', ui-monospace, monospace",
};

type ChromeProps = { children: React.ReactNode; title?: string; chrome?: ChromeApi };
function DeckChrome({ children, title = "DECK//OS v0.4.1", chrome }: ChromeProps) {
  // Chrome theme matches DeckOS palette: phosphor green on near-black.
  const chromeTheme = {
    bg: "rgba(155,242,192,0.06)",
    fg: DECK.ink,
    border: DECK.rule,
    font: DECK.font,
    mono: DECK.font,
    height: 76,
    radius: 2,
    padding: "0 18px",
  };
  return (
    <div style={{
      width: 1280, height: 800, background: DECK.bg, color: DECK.ink, fontFamily: DECK.font,
      position: "relative", overflow: "hidden",
      backgroundImage:
        "repeating-linear-gradient(0deg, rgba(155,242,192,0.025) 0 1px, transparent 1px 3px)," +
        "radial-gradient(ellipse at 50% 50%, rgba(155,242,192,0.06), transparent 70%)",
    }}>
      {/* Top chrome bar — interactive. 96 px tall in design coords (≈58 px
       * on the 5″ screen at 0.6 scale). Decorative status text trimmed to
       * make room; a small "DECK//OS" plate retains skin identity. */}
      <div style={{
        height: 96, display: "flex", alignItems: "center", padding: "0 20px", gap: 12,
        borderBottom: `1px solid ${DECK.rule}`, background: DECK.panel,
        fontSize: 13, letterSpacing: "0.08em", textTransform: "uppercase",
      }}>
        <span style={{color: DECK.mag, fontWeight: 700, fontSize: 14, letterSpacing: "0.12em", flexShrink: 0}}>● {title}</span>
        <span style={{flex: 1}}/>
        {chrome && (
          <>
            <ChromeSourceBtn chrome={chrome} theme={chromeTheme}/>
            <ChromeQueueBtn chrome={chrome} theme={chromeTheme}/>
            <ChromeSkinBtn chrome={chrome} theme={chromeTheme}/>
            <ChromeSettingsBtn chrome={chrome} theme={chromeTheme}/>
          </>
        )}
      </div>
      {children}
    </div>
  );
}

type AsciiBarProps = { value: number; width?: number; color?: string; peakColor?: string; label?: string };
function AsciiBar({ value, width = 36, color = DECK.ink, peakColor = DECK.mag, label }: AsciiBarProps) {
  const fill = Math.round(value * width);
  const out: string[] = [];
  for (let i = 0; i < width; i++) {
    if (i < fill - 1)        out.push("█");
    else if (i === fill - 1) out.push("▓");
    else if (i === fill)     out.push("░");
    else                     out.push("·");
  }
  return (
    <div style={{display: "flex", alignItems: "center", gap: 10, fontFamily: DECK.font, fontSize: 14, lineHeight: 1}}>
      {label && <span style={{color: DECK.ink2, width: 42}}>{label}</span>}
      <span style={{letterSpacing: "0.05em"}}>
        {out.map((ch, i) => (
          <span key={i} style={{
            color: i < fill ? (i > width * 0.85 ? peakColor : color) : DECK.dim,
          }}>{ch}</span>
        ))}
      </span>
    </div>
  );
}

type DeckBtnProps = {
  children?: React.ReactNode;
  active?: boolean;
  big?: boolean;
  onClick?: () => void;
  w?: number | string;
  h?: number | string;
};
function DeckBtn({ children, active, big, onClick, w, h }: DeckBtnProps) {
  const color = active ? DECK.mag : DECK.ink;
  return (
    <button onClick={onClick} style={{
      width: w ?? (big ? 168 : 110), height: h ?? (big ? 110 : 84),
      background: active ? "rgba(255,79,168,0.08)" : "rgba(155,242,192,0.04)",
      border: `1.5px solid ${active ? DECK.mag : DECK.rule}`,
      color, fontFamily: DECK.font, fontSize: big ? 16 : 13, fontWeight: 700,
      letterSpacing: "0.12em", textTransform: "uppercase", cursor: "pointer",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 6,
      boxShadow: active ? `0 0 0 1px ${DECK.mag} inset, 0 0 24px rgba(255,79,168,0.25)` : "none",
      transition: "all .12s",
      borderRadius: 2,
    }}>{children}</button>
  );
}

// ---------- Audio (Now Playing) -------------------------------------------

export type DeckosAudioProps = {
  track: Track | null;
  state: PlayState;
  elapsed: number;          // seconds
  volume: number | null;    // 0..100 or null
  shuffle?: boolean;
  repeat?: boolean;
  onToggle?: () => void;
  onNext?: () => void;
  onPrev?: () => void;
  onToggleShuffle?: () => void;
  onToggleRepeat?: () => void;
};

export function DeckosAudio({ track, state, elapsed, volume, shuffle, repeat, chrome, onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek }: DeckosAudioProps & { chrome?: ChromeApi; onSeek?: (sec: number) => void }) {
  const playing = state === "playing";
  const t = useTicker(80);
  const tr = track ?? { uri: "", title: "—", artist: "—", album: "—", len: 0, time: "0:00" };
  const len = tr.len > 0 ? tr.len : 1;
  const pct = Math.min(1, elapsed / len);

  // Real audio spectrum (live PipeWire tap). Renders peak-hold envelope so
  // the bars react instantly to transients but linger long enough to read.
  // No demo-oscillator fallback any more — when audio is silent we WANT to
  // show flat bars, not a fake animation.
  const spec = useSpectrum();
  const bars = Array.from(spec.peaks);
  const lpeak = spec.rmsL;
  const rpeak = spec.rmsR;
  const volPct = (volume ?? 62) / 100;
  void t; void vu;

  return (
    <DeckChrome title="DECK//OS" chrome={chrome}>
      <div style={{padding: "24px 28px", display: "grid", gridTemplateColumns: "1fr 360px", gap: 28, height: "calc(100% - 96px)"}}>
        {/* Left: track + spectrum */}
        <div style={{display: "flex", flexDirection: "column", gap: 18, minHeight: 0}}>
          {/* Track ID block */}
          <div style={{border: `1px solid ${DECK.rule}`, padding: "18px 22px", background: DECK.panel,
            display: "flex", alignItems: "center", gap: 18, minWidth: 0}}>
            <AlbumThumb artist={tr.artist} album={tr.album} track={tr.title} seed={tr.uri} size={88} radius={4}/>
            <div style={{flex: 1, minWidth: 0}}>
              <div style={{fontSize: 11, color: DECK.ink2, letterSpacing: "0.18em", marginBottom: 10}}>
                ┌── NOW PLAYING ── DEVICE:LOCAL ── DAC pcm5122
              </div>
              <div style={{
                fontSize: 38, fontWeight: 700, color: DECK.ink, lineHeight: 1.05, letterSpacing: "-0.01em",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {tr.title}<span style={{color: DECK.mag}}>_</span>
              </div>
              <div style={{
                fontSize: 18, color: DECK.cyan, marginTop: 6,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {tr.artist} <span style={{color: DECK.dim}}>//</span> <span style={{color: DECK.ink2}}>{tr.album || "—"}</span>
              </div>
            </div>
          </div>

          {/* Spectrum */}
          <div style={{border: `1px solid ${DECK.rule}`, padding: "14px 18px", background: DECK.panel, flex: 1, display: "flex", flexDirection: "column"}}>
            <div style={{fontSize: 11, color: DECK.ink2, letterSpacing: "0.18em", marginBottom: 10}}>
              ── FFT 64-BAND ── PRE-EQ ──
            </div>
            <div style={{flex: 1, display: "flex", alignItems: "flex-end", gap: 3, paddingBottom: 4}}>
              {bars.map((v, i) => {
                const h = 6 + v * 100;
                const hot = v > 0.85;
                return (
                  <div key={i} style={{
                    flex: 1, height: `${h}%`,
                    background: hot ? DECK.mag : (v > 0.5 ? DECK.ink : DECK.ink2),
                    boxShadow: hot ? `0 0 8px ${DECK.mag}` : "none",
                    minHeight: 2,
                  }}/>
                );
              })}
            </div>
            <div style={{display: "flex", justifyContent: "space-between", color: DECK.dim, fontSize: 10, letterSpacing: "0.18em", marginTop: 6}}>
              <span>20Hz</span><span>200</span><span>2k</span><span>20kHz</span>
            </div>
          </div>

          {/* Progress as ASCII bar */}
          <div style={{border: `1px solid ${DECK.rule}`, padding: "14px 18px", background: DECK.panel, fontFamily: DECK.font}}>
            <div style={{display: "flex", justifyContent: "space-between", fontSize: 13, color: DECK.ink2, marginBottom: 6}}>
              <span style={{color: DECK.amber, fontVariantNumeric: "tabular-nums"}}>{mmss(elapsed)}</span>
              <span style={{color: DECK.dim, fontSize: 11, letterSpacing: "0.12em"}}>POSITION</span>
              <span style={{color: DECK.amber, fontVariantNumeric: "tabular-nums"}}>−{mmss(Math.max(0, len - elapsed))}</span>
            </div>
            <SeekableBar value={pct} lengthSec={len} onSeek={onSeek}>
              <AsciiBar value={pct} width={70} color={DECK.cyan} peakColor={DECK.mag} />
            </SeekableBar>
          </div>
        </div>

        {/* Right: meters + transport */}
        <div style={{display: "flex", flexDirection: "column", gap: 14}}>
          <div style={{border: `1px solid ${DECK.rule}`, padding: "14px 18px", background: DECK.panel}}>
            <div style={{fontSize: 11, color: DECK.ink2, letterSpacing: "0.18em", marginBottom: 14}}>── VU // PEAK ──</div>
            <div style={{display: "flex", flexDirection: "column", gap: 8}}>
              <AsciiBar value={lpeak} width={28} label="L"/>
              <AsciiBar value={rpeak} width={28} label="R"/>
            </div>
            <div style={{fontSize: 11, color: DECK.dim, letterSpacing: "0.18em", marginTop: 14, display: "flex", justifyContent: "space-between"}}>
              <span>−∞</span><span>−24</span><span>−12</span><span>−6</span><span>0</span><span style={{color: DECK.red}}>+3</span>
            </div>
          </div>

          {/* Transport */}
          <div style={{border: `1px solid ${DECK.rule}`, padding: 18, background: DECK.panel, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10}}>
            <DeckBtn onClick={onPrev}>{"<<"}<span style={{fontSize: 9, color: DECK.dim}}>PREV</span></DeckBtn>
            <DeckBtn onClick={onNext}>{">>"}<span style={{fontSize: 9, color: DECK.dim}}>NEXT</span></DeckBtn>
            <div style={{gridColumn: "1 / -1"}}>
              <DeckBtn big w="100%" h={140} active={playing} onClick={onToggle}>
                <span style={{fontSize: 48, lineHeight: 1}}>{playing ? "▮▮" : "▶"}</span>
                <span style={{fontSize: 11, color: playing ? DECK.mag : DECK.ink2, letterSpacing: "0.2em"}}>
                  {playing ? "[ PAUSE ]" : "[ PLAY ]"}
                </span>
              </DeckBtn>
            </div>
            <DeckBtn active={shuffle} onClick={onToggleShuffle}>SHUF<span style={{fontSize: 9, color: DECK.dim}}>⇄</span></DeckBtn>
            <DeckBtn active={repeat} onClick={onToggleRepeat}>RPT<span style={{fontSize: 9, color: DECK.dim}}>↻</span></DeckBtn>
          </div>

          {/* Volume */}
          <div style={{border: `1px solid ${DECK.rule}`, padding: "14px 18px", background: DECK.panel}}>
            <div style={{fontSize: 11, color: DECK.ink2, letterSpacing: "0.18em", marginBottom: 10, display: "flex", justifyContent: "space-between"}}>
              <span>VOL</span>
              <span style={{color: DECK.amber}}>{volume == null ? "—" : `${volume}/100`}</span>
            </div>
            <AsciiBar value={volPct} width={28} color={DECK.cyan} peakColor={DECK.amber}/>
          </div>
        </div>
      </div>
    </DeckChrome>
  );
}

// ---------- Source switcher (carried from source.jsx, mock-only for v1) ---

export function DeckosSource() {
  const [sel, setSel] = React.useState("local");
  return (
    <DeckChrome title="DECK//OS · INPUT.SELECT">
      <div style={{padding: "28px 32px", height: "calc(100% - 44px)", display: "flex", flexDirection: "column"}}>
        <div style={{fontSize: 14, color: DECK.ink2, letterSpacing: "0.18em", marginBottom: 24}}>
          $ <span style={{color: DECK.mag}}>boombox</span>:~ select-input <span style={{color: DECK.cyan}}>--list</span>
        </div>
        <div style={{display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, flex: 1}}>
          {SOURCES.map((s, i) => {
            const active = sel === s.id;
            return (
              <button key={s.id} onClick={() => setSel(s.id)} style={{
                background: active ? "rgba(255,79,168,0.08)" : DECK.panel,
                border: `1.5px solid ${active ? DECK.mag : DECK.rule}`,
                padding: "22px 24px", textAlign: "left", cursor: "pointer", color: DECK.ink,
                fontFamily: DECK.font, position: "relative",
                boxShadow: active ? `0 0 24px rgba(255,79,168,0.2)` : "none",
                display: "flex", flexDirection: "column", gap: 10,
              }}>
                <div style={{display: "flex", alignItems: "center", justifyContent: "space-between"}}>
                  <span style={{fontSize: 11, color: active ? DECK.mag : DECK.ink2, letterSpacing: "0.18em"}}>
                    [ {String(i).padStart(2, "0")} ]
                  </span>
                  <span style={{fontSize: 11, color: active ? DECK.mag : DECK.dim, letterSpacing: "0.18em"}}>
                    {active ? "● ACTIVE" : "○ STANDBY"}
                  </span>
                </div>
                <div style={{fontSize: 32, fontWeight: 700, letterSpacing: "-0.01em", color: DECK.ink}}>
                  {s.label}
                </div>
                <div style={{fontSize: 13, color: DECK.ink2}}>
                  {s.sub}
                </div>
                <div style={{marginTop: "auto", borderTop: `1px solid ${DECK.rule}`, paddingTop: 10, fontSize: 11, color: DECK.dim, letterSpacing: "0.14em"}}>
                  <AsciiBar value={active ? 0.85 : 0.15 + i * 0.08} width={22} color={active ? DECK.mag : DECK.ink2} peakColor={DECK.mag}/>
                </div>
              </button>
            );
          })}
        </div>
        <div style={{marginTop: 24, display: "flex", gap: 14, alignItems: "center"}}>
          <DeckBtn active>↵ CONFIRM</DeckBtn>
          <DeckBtn>ESC CANCEL</DeckBtn>
          <span style={{flex: 1}}></span>
          <span style={{color: DECK.ink2, fontSize: 13}}>
            <span style={{color: DECK.mag}}>{sel.toUpperCase()}</span> selected · stream will reroute on confirm
          </span>
        </div>
      </div>
    </DeckChrome>
  );
}
