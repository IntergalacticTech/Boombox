// BLOCK 95 — adapted from skins/block95/source.jsx
// Chunky 90s portable boombox plastic, FLAT.
import React from "react";
import { Icon, useTicker, vu, mmss } from "../../lib/shared";
import { useSpectrum } from "../../lib/spectrum";
import { ChromeSourceBtn, ChromeQueueBtn, ChromeSkinBtn, ChromeSettingsBtn } from "../../lib/ChromeButtons";
import { SeekableBar } from "../../lib/SeekableBar";
import type { ChromeApi } from "../../lib/skinRegistry";
import type { Track, PlayState } from "../../lib/types";

const B95 = {
  yellow:   "#ffd400",
  magenta:  "#ff2d8a",
  cyan:     "#00d3e6",
  blue:     "#1c2bff",
  black:    "#0c0c0c",
  white:    "#fafaf6",
  paper:    "#eee8d8",
  font:     "'Archivo Black', 'Inter', system-ui, sans-serif",
  mono:     "'JetBrains Mono', monospace",
};

function B95Chrome({ children, header = "NOW PLAYING", chrome }: { children: React.ReactNode; header?: string; chrome?: ChromeApi }) {
  // Block95 chrome: cyan/black plastic buttons on the yellow header.
  const chromeTheme = {
    bg: B95.cyan,
    fg: B95.black,
    border: B95.black,
    font: B95.font,
    mono: B95.mono,
    height: 60,
    radius: 0,
    padding: "0 14px",
  };
  return (
    <div style={{
      width: 1280, height: 800, background: B95.black, color: B95.white,
      fontFamily: "'Inter', system-ui, sans-serif", overflow: "hidden", position: "relative",
    }}>
      <div style={{
        height: 96, padding: "0 24px", display: "flex", alignItems: "center", gap: 14,
        background: B95.yellow, color: B95.black, borderBottom: `6px solid ${B95.black}`,
      }}>
        <div style={{fontFamily: B95.font, fontSize: 26, letterSpacing: "-0.02em", flexShrink: 0}}>BOOMBOX/95</div>
        <div style={{fontFamily: B95.mono, fontSize: 12, fontWeight: 600, letterSpacing: "0.18em", padding: "4px 10px", background: B95.black, color: B95.yellow, flexShrink: 0}}>
          {header}
        </div>
        <div style={{flex: 1}}></div>
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

type B95BtnProps = {
  children?: React.ReactNode;
  color?: string; fg?: string;
  w?: number | null; h?: number;
  big?: boolean; active?: boolean;
  onClick?: () => void;
};
function B95Btn({ children, color = B95.white, fg = B95.black, w, h = 100, big, active, onClick }: B95BtnProps) {
  // When `w` is null (button used inside a grid cell) we let it fill the cell;
  // otherwise an explicit pixel width wins. Original code defaulted to 132/220
  // which made the wide PLAY button overflow its 1fr cell on the 800px screen.
  const widthStyle = w === null ? "100%" : (w ?? (big ? 220 : 132));
  return (
    <button onClick={onClick} style={{
      width: widthStyle, height: big ? 140 : h,
      background: color, color: fg,
      border: "none", outline: `4px solid ${B95.black}`,
      outlineOffset: -4,
      cursor: "pointer", position: "relative",
      fontFamily: B95.font, fontSize: big ? 22 : 16, letterSpacing: "-0.01em",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 4,
      boxShadow: active ? `8px 8px 0 ${B95.magenta}` : `6px 6px 0 ${B95.black}`,
      transform: active ? "translate(2px, 2px)" : "translate(0,0)",
      transition: "transform .08s, box-shadow .08s",
    }}>{children}</button>
  );
}

export type Block95AudioProps = {
  track: Track | null;
  state: PlayState;
  elapsed: number;
  volume: number | null;
  shuffle?: boolean;
  repeat?: boolean;
  onToggle?: () => void;
  onNext?: () => void;
  onPrev?: () => void;
  onToggleShuffle?: () => void;
  onToggleRepeat?: () => void;
};

export function Block95Audio({ track, state, elapsed, volume, shuffle, repeat, chrome, onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek }: Block95AudioProps & { chrome?: ChromeApi; onSeek?: (sec: number) => void }) {
  const playing = state === "playing";
  const t = useTicker(80);
  const tr = track ?? { title: "—", artist: "—", album: "—", len: 0, time: "0:00" };
  const len = tr.len > 0 ? tr.len : 1;
  const pct = Math.min(1, elapsed / len);
  const segs = (val: number) => Array.from({length: 12}, (_, i) => i < Math.round(val * 12));
  const spec = useSpectrum();
  const lvu = segs(spec.rmsL);
  const rvu = segs(spec.rmsR);
  void t; void vu;
  const volPct = (volume ?? 62) / 100;
  const volSegs = Math.round(volPct * 24);

  return (
    <B95Chrome header={playing ? "01 NOW PLAYING" : "01 PAUSED"} chrome={chrome}>
      <div style={{padding: 24, height: "calc(100% - 96px)", display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: 24, minWidth: 0}}>
        <div style={{display: "flex", flexDirection: "column", gap: 18, minHeight: 0, minWidth: 0}}>
          <div style={{flex: 1, background: B95.magenta, color: B95.black, padding: "32px 32px",
            display: "flex", flexDirection: "column", justifyContent: "space-between", border: `6px solid ${B95.black}`, minWidth: 0}}>
            <div>
              <div style={{fontFamily: B95.mono, fontSize: 13, fontWeight: 700, letterSpacing: "0.22em"}}>
                NOW PLAYING — LOCAL
              </div>
              <div style={{
                fontFamily: B95.font, fontSize: 78, lineHeight: 0.92, letterSpacing: "-0.04em", marginTop: 14,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {tr.title}
              </div>
            </div>
            <div>
              <div style={{
                fontFamily: B95.font, fontSize: 30, lineHeight: 1, letterSpacing: "-0.02em",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {tr.artist}
              </div>
              <div style={{fontFamily: B95.mono, fontSize: 14, fontWeight: 600, marginTop: 6, letterSpacing: "0.04em"}}>
                {tr.album || "—"}
              </div>
            </div>
          </div>

          <div style={{background: B95.cyan, color: B95.black, padding: "18px 22px", border: `6px solid ${B95.black}`}}>
            <div style={{display: "flex", justifyContent: "space-between", fontFamily: B95.mono, fontSize: 14, fontWeight: 700, marginBottom: 10}}>
              <span>{mmss(elapsed)}</span>
              <span style={{letterSpacing: "0.22em"}}>—— PROGRESS ——</span>
              <span>−{mmss(Math.max(0, len - elapsed))}</span>
            </div>
            <SeekableBar value={pct} lengthSec={len} onSeek={onSeek}>
              <div style={{height: 18, background: B95.black, position: "relative", padding: 2}}>
                <div style={{height: "100%", width: `${pct * 100}%`, background: `repeating-linear-gradient(90deg, ${B95.yellow} 0 14px, ${B95.cyan} 14px 16px)`}}/>
              </div>
            </SeekableBar>
          </div>
        </div>

        <div style={{display: "flex", flexDirection: "column", gap: 16, minWidth: 0}}>
          <div style={{background: B95.white, color: B95.black, padding: "18px 20px", border: `6px solid ${B95.black}`}}>
            <div style={{fontFamily: B95.font, fontSize: 18, marginBottom: 14, letterSpacing: "-0.01em"}}>VU LEVELS</div>
            {[{l: "L", a: lvu}, {l: "R", a: rvu}].map((row, ri) => (
              <div key={ri} style={{display: "flex", alignItems: "center", gap: 10, marginBottom: 8}}>
                <div style={{fontFamily: B95.font, fontSize: 24, width: 24}}>{row.l}</div>
                <div style={{flex: 1, display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 4}}>
                  {row.a.map((on, i) => {
                    const c = i < 7 ? B95.cyan : i < 10 ? B95.yellow : B95.magenta;
                    return <div key={i} style={{height: 22, background: on ? c : "#e6e2d2", border: `2px solid ${B95.black}`}}/>;
                  })}
                </div>
              </div>
            ))}
            <div style={{display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 4, paddingLeft: 34, marginTop: 6,
              fontFamily: B95.mono, fontSize: 9, fontWeight: 700, color: B95.black, letterSpacing: "0.02em"}}>
              {["−40", "", "", "−20", "", "", "−12", "−6", "−3", "0", "+3", ""].map((v, i) =>
                <div key={i} style={{textAlign: "center"}}>{v}</div>
              )}
            </div>
          </div>

          <div style={{display: "grid", gridTemplateColumns: "1fr 1.6fr 1fr", gap: 14, minWidth: 0}}>
            <B95Btn color={B95.white} h={120} w={null} onClick={onPrev}><Icon name="prev" size={36} stroke={B95.black} sw={2.5}/>PREV</B95Btn>
            <B95Btn big color={playing ? B95.yellow : B95.cyan} active w={null} onClick={onToggle}>
              <Icon name={playing ? "pause" : "play"} size={56} stroke={B95.black} sw={2.5}/>
              {playing ? "PAUSE" : "PLAY"}
            </B95Btn>
            <B95Btn color={B95.white} h={120} w={null} onClick={onNext}><Icon name="next" size={36} stroke={B95.black} sw={2.5}/>NEXT</B95Btn>
          </div>
          <div style={{display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10}}>
            <B95Btn color={shuffle ? B95.yellow : B95.cyan} h={80} w={null} active={shuffle} onClick={onToggleShuffle}><Icon name="shuffle" size={24} stroke={B95.black} sw={2.5}/></B95Btn>
            <B95Btn color={repeat ? B95.yellow : B95.cyan} h={80} w={null} active={repeat} onClick={onToggleRepeat}><Icon name="repeat" size={24} stroke={B95.black} sw={2.5}/></B95Btn>
            <B95Btn color={B95.magenta} h={80} w={null} fg={B95.white}><Icon name="queue" size={24} stroke={B95.white} sw={2.5}/></B95Btn>
            <B95Btn color={B95.magenta} h={80} w={null} fg={B95.white}><Icon name="search" size={24} stroke={B95.white} sw={2.5}/></B95Btn>
          </div>

          <div style={{background: B95.black, color: B95.yellow, padding: "14px 18px", border: `4px solid ${B95.yellow}`, display: "flex", alignItems: "center", gap: 14}}>
            <span style={{fontFamily: B95.font, fontSize: 20}}>VOL</span>
            <div style={{flex: 1, display: "flex", gap: 3}}>
              {Array.from({length: 24}).map((_, i) => (
                <div key={i} style={{flex: 1, height: 22, background: i < volSegs ? B95.yellow : "#3a3a30"}}/>
              ))}
            </div>
            <span style={{fontFamily: B95.mono, fontSize: 14, fontWeight: 700, minWidth: 48, textAlign: "right"}}>{volume ?? "—"}%</span>
          </div>
        </div>
      </div>
    </B95Chrome>
  );
}
