// SPECTRUM — adapted from skins/spectrum/source.jsx
// Visualizer-first immersive: radial spectrum + glass tray.
import React from "react";
import { Icon, useTicker, vu, mmss } from "../../lib/shared";
import { useSpectrum } from "../../lib/spectrum";
import { ChromeSourceBtn, ChromeQueueBtn, ChromeSkinBtn, ChromeSettingsBtn } from "../../lib/ChromeButtons";
import { SeekableBar } from "../../lib/SeekableBar";
import type { ChromeApi } from "../../lib/skinRegistry";
import type { Track, PlayState } from "../../lib/types";

const SPC = {
  bg:       "#070a14",
  ink:      "#e9ecf2",
  ink2:     "#8a93b0",
  glass:    "rgba(255,255,255,0.06)",
  glassHi:  "rgba(255,255,255,0.12)",
  rule:     "rgba(255,255,255,0.12)",
  cyan:     "#5be7ff",
  violet:   "#b794ff",
  amber:    "#ffb84d",
  red:      "#ff5466",
  font:     "'Space Grotesk', system-ui, -apple-system, sans-serif",
  mono:     "'JetBrains Mono', monospace",
};

function SpcChrome({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      width: 1280, height: 800, background: SPC.bg, color: SPC.ink, fontFamily: SPC.font,
      position: "relative", overflow: "hidden",
    }}>{children}</div>
  );
}

type SpcBtnProps = {
  children?: React.ReactNode;
  w?: number; h?: number;
  big?: boolean; active?: boolean; primary?: boolean;
  onClick?: () => void;
};
function SpcBtn({ children, w, h = 92, big, active, primary, onClick }: SpcBtnProps) {
  return (
    <button onClick={onClick} style={{
      width: w ?? (big ? 180 : 110),
      height: big ? 120 : h,
      background: primary ? SPC.ink : (active ? SPC.glassHi : SPC.glass),
      color: primary ? SPC.bg : SPC.ink,
      backdropFilter: "blur(20px)",
      border: `1px solid ${primary ? SPC.ink : SPC.rule}`,
      borderRadius: big ? 24 : 18,
      cursor: "pointer",
      fontFamily: SPC.font, fontSize: big ? 15 : 13, fontWeight: 600, letterSpacing: "0.14em", textTransform: "uppercase",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 4,
      transition: "all .12s",
    }}>{children}</button>
  );
}

function RadialSpectrum({ size = 560, playing = true }: { size?: number; playing?: boolean }) {
  const t = useTicker(60);
  const spec = useSpectrum();
  const N = 96;
  return (
    <svg width={size} height={size} viewBox={`-${size / 2} -${size / 2} ${size} ${size}`} style={{display: "block"}}>
      <defs>
        <radialGradient id="spcGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={SPC.cyan} stopOpacity="0.25"/>
          <stop offset="60%" stopColor={SPC.violet} stopOpacity="0.08"/>
          <stop offset="100%" stopColor="transparent"/>
        </radialGradient>
      </defs>
      <circle cx="0" cy="0" r={size * 0.42} fill="url(#spcGlow)"/>
      {[0.30, 0.36, 0.46].map((r, i) => (
        <circle key={i} cx="0" cy="0" r={size * r} fill="none" stroke={SPC.rule} strokeWidth="0.8" strokeDasharray={i === 2 ? "2 4" : ""}/>
      ))}
      {Array.from({length: N}).map((_, i) => {
        const a = (i / N) * Math.PI * 2;
        // Real spectrum has 64 bins; spread them across 96 visual rays by
        // index-mapping (each ray pulls from its nearest peak).
        const bin = Math.min(63, Math.floor((i / N) * 64));
        const v = spec.peaks[bin];
        void t; void vu; void playing;
        const r1 = size * 0.32;
        const r2 = r1 + v * (size * 0.12);
        const x1 = Math.cos(a) * r1, y1 = Math.sin(a) * r1;
        const x2 = Math.cos(a) * r2, y2 = Math.sin(a) * r2;
        const hot = v > 0.85;
        return (
          <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
            stroke={hot ? SPC.amber : (i % 4 === 0 ? SPC.cyan : SPC.violet)}
            strokeOpacity={0.55 + v * 0.45}
            strokeWidth={2.2} strokeLinecap="round"/>
        );
      })}
      {[0, 1, 2, 3].map(i => {
        const a = i * 90 + (t * 0.4 % 360);
        const r = size * 0.46;
        return <path key={i} d={`M ${Math.cos(a * Math.PI / 180) * r} ${Math.sin(a * Math.PI / 180) * r} A ${r} ${r} 0 0 1 ${Math.cos((a + 24) * Math.PI / 180) * r} ${Math.sin((a + 24) * Math.PI / 180) * r}`}
          fill="none" stroke={SPC.cyan} strokeWidth="1.5" strokeOpacity="0.7"/>;
      })}
      <circle cx="0" cy="0" r="3" fill={SPC.amber}/>
    </svg>
  );
}

function WaveStrip({ height = 60, playing = true }: { height?: number; playing?: boolean }) {
  const t = useTicker(80);
  const spec = useSpectrum();
  const N = 220;
  return (
    <svg width="100%" viewBox={`0 -${height / 2} ${N} ${height}`} preserveAspectRatio="none" style={{height, display: "block"}}>
      {Array.from({length: N}).map((_, i) => {
        const bin = Math.min(63, Math.floor((i / N) * 64));
        const v = spec.bins[bin] * 0.9 + 0.1;
        void t; void vu; void playing;
        return <line key={i} x1={i + 0.5} x2={i + 0.5} y1={-v * height / 2} y2={v * height / 2}
          stroke={i % 12 === 0 ? SPC.amber : SPC.cyan} strokeOpacity={0.6 + v * 0.4} strokeWidth="0.8"/>;
      })}
    </svg>
  );
}

export type SpectrumAudioProps = {
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

export function SpectrumAudio({ track, state, elapsed, volume, shuffle, repeat, chrome, onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek }: SpectrumAudioProps & { chrome?: ChromeApi; onSeek?: (sec: number) => void }) {
  const playing = state === "playing";
  const tr = track ?? { title: "—", artist: "—", album: "—", len: 0, time: "0:00" };
  const len = tr.len > 0 ? tr.len : 1;
  const pct = Math.min(1, elapsed / len);
  const volPct = (volume ?? 62) / 100;

  return (
    <SpcChrome>
      <div style={{position: "absolute", inset: 0,
        background: `radial-gradient(circle at 30% 30%, rgba(91,231,255,0.15), transparent 50%),
                    radial-gradient(circle at 70% 70%, rgba(183,148,255,0.18), transparent 55%),
                    linear-gradient(180deg, #07091a 0%, #050714 100%)`}}/>
      <div style={{position: "absolute", top: 20, left: 28, right: 28, display: "flex", alignItems: "center", gap: 12, zIndex: 5}}>
        <div style={{padding: "12px 18px", background: SPC.glass, border: `1px solid ${SPC.rule}`, borderRadius: 999, backdropFilter: "blur(12px)", fontFamily: SPC.mono, fontSize: 12, letterSpacing: "0.22em", textTransform: "uppercase"}}>
          <span style={{color: SPC.amber}}>●</span> {playing ? "Now Playing" : "Paused"} · Local
        </div>
        <div style={{flex: 1}}></div>
        {chrome && (
          <>
            <ChromeSourceBtn chrome={chrome} theme={{
              bg: SPC.glass, fg: SPC.ink, border: SPC.rule,
              font: SPC.font, mono: SPC.mono, height: 56, radius: 999, padding: "0 16px",
            }}/>
            <ChromeQueueBtn chrome={chrome} theme={{
              bg: SPC.glass, fg: SPC.ink, border: SPC.rule,
              font: SPC.font, mono: SPC.mono, height: 56, radius: 999, padding: "0 16px",
            }}/>
            <ChromeSkinBtn chrome={chrome} theme={{
              bg: SPC.glass, fg: SPC.ink, border: SPC.rule,
              font: SPC.font, mono: SPC.mono, height: 56, radius: 999, padding: "0 16px",
            }}/>
            <ChromeSettingsBtn chrome={chrome} theme={{
              bg: SPC.glass, fg: SPC.ink, border: SPC.rule,
              font: SPC.font, mono: SPC.mono, height: 56, radius: 999, padding: "0 16px",
            }}/>
          </>
        )}
      </div>

      <div style={{position: "absolute", top: 80, left: 0, right: 0, display: "flex", justifyContent: "center"}}>
        <div style={{position: "relative", width: 560, height: 560}}>
          <RadialSpectrum size={560} playing={playing}/>
          <div style={{position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", gap: 6, pointerEvents: "none"}}>
            <div style={{fontFamily: SPC.mono, fontSize: 11, letterSpacing: "0.32em", textTransform: "uppercase", color: SPC.cyan}}>{playing ? "Now Playing" : "Paused"}</div>
            <div style={{fontFamily: SPC.font, fontWeight: 700, fontSize: 46, lineHeight: 1.02, letterSpacing: "-0.02em", maxWidth: 340,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis"}}>
              {tr.title}
            </div>
            <div style={{fontFamily: SPC.font, fontSize: 18, color: SPC.ink2, marginTop: 4,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 340}}>{tr.artist}</div>
            <div style={{fontFamily: SPC.mono, fontSize: 11, color: SPC.ink2, marginTop: 2, letterSpacing: "0.18em",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 340}}>{(tr.album || "—").toUpperCase()}</div>
          </div>
        </div>
      </div>

      <div style={{position: "absolute", left: 24, right: 24, bottom: 24,
        background: "rgba(8,12,28,0.55)", backdropFilter: "blur(28px)",
        border: `1px solid ${SPC.rule}`, borderRadius: 28, padding: "18px 22px",
        boxShadow: "0 24px 60px rgba(0,0,0,0.45)"}}>
        <SeekableBar value={pct} lengthSec={len} onSeek={onSeek} style={{marginBottom: 14}}>
          <div style={{position: "relative", height: 60}}>
            <WaveStrip playing={playing}/>
            <div style={{position: "absolute", left: `${pct * 100}%`, top: -4, bottom: -4, width: 2, background: SPC.amber, boxShadow: `0 0 12px ${SPC.amber}`}}/>
          </div>
        </SeekableBar>
        <div style={{display: "flex", alignItems: "center", gap: 14}}>
          <div style={{fontFamily: SPC.mono, fontSize: 13, fontVariantNumeric: "tabular-nums", letterSpacing: "0.08em", width: 80}}>
            <div style={{color: SPC.amber}}>{mmss(elapsed)}</div>
            <div style={{color: SPC.ink2, fontSize: 11}}>/ {tr.time}</div>
          </div>
          <div style={{flex: 1}}></div>
          <SpcBtn active={shuffle} onClick={onToggleShuffle}><Icon name="shuffle" size={22}/></SpcBtn>
          <SpcBtn w={100} onClick={onPrev}><Icon name="prev" size={26}/></SpcBtn>
          <SpcBtn big primary onClick={onToggle}>
            <Icon name={playing ? "pause" : "play"} size={40} stroke={SPC.bg}/>
          </SpcBtn>
          <SpcBtn w={100} onClick={onNext}><Icon name="next" size={26}/></SpcBtn>
          <SpcBtn active={repeat} onClick={onToggleRepeat}><Icon name="repeat" size={22}/></SpcBtn>
          <div style={{flex: 1}}></div>
          <div style={{display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", background: SPC.glass, border: `1px solid ${SPC.rule}`, borderRadius: 18, width: 200}}>
            <Icon name="vol" size={22}/>
            <div style={{flex: 1, height: 4, background: "rgba(255,255,255,0.18)", borderRadius: 2, position: "relative"}}>
              <div style={{height: "100%", width: `${volPct * 100}%`, background: SPC.cyan, borderRadius: 2}}/>
              <div style={{position: "absolute", left: `${volPct * 100}%`, top: -6, width: 14, height: 14, borderRadius: "50%", background: SPC.ink, border: `2px solid ${SPC.bg}`, transform: "translateX(-50%)"}}/>
            </div>
          </div>
        </div>
      </div>
    </SpcChrome>
  );
}
