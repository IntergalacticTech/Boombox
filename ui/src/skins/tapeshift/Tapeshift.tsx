// TAPE//SHIFT — adapted from skins/tapeshift/source.jsx
// Horizontal "reel" of sources/tracks · cassette-as-data without drawing one.
import React from "react";
import { Icon, useTicker, vu, mmss, TRACKS } from "../../lib/shared";
import { useSpectrum } from "../../lib/spectrum";
import { ChromeSourceBtn, ChromeQueueBtn, ChromeSkinBtn, ChromeSettingsBtn } from "../../lib/ChromeButtons";
import { SeekableBar } from "../../lib/SeekableBar";
import type { ChromeApi } from "../../lib/skinRegistry";
import type { Track, PlayState } from "../../lib/types";

const TS = {
  bg:       "#161410",
  panel:    "#1f1c17",
  panelHi:  "#28241e",
  ink:      "#f3ece0",
  ink2:     "#a39684",
  rule:     "rgba(243,236,224,0.10)",
  ruleHi:   "rgba(243,236,224,0.18)",
  ember:    "#ff7a35",
  lime:     "#c8e44a",
  cyan:     "#7fd9d4",
  red:      "#ff5253",
  font:     "'Space Grotesk', system-ui, sans-serif",
  mono:     "'JetBrains Mono', monospace",
};

function TsChrome({ children, label, chrome }: { children: React.ReactNode; label: string; chrome?: ChromeApi }) {
  // Tapeshift chrome: warm tape look with ember + cyan accents.
  const chromeTheme = {
    bg: TS.panel,
    fg: TS.ink,
    border: TS.ruleHi,
    font: TS.font,
    mono: TS.mono,
    height: 60,
    radius: 8,
    padding: "0 14px",
  };
  return (
    <div style={{
      width: 1280, height: 800, background: TS.bg, color: TS.ink, fontFamily: TS.font,
      position: "relative", overflow: "hidden",
    }}>
      <div style={{
        height: 96, padding: "0 24px", display: "flex", alignItems: "center", gap: 14,
        borderBottom: `1px solid ${TS.rule}`, fontFamily: TS.mono, fontSize: 12,
        letterSpacing: "0.22em", textTransform: "uppercase", color: TS.ink2,
      }}>
        <span style={{color: TS.ember, fontWeight: 700, flexShrink: 0}}>▮▮▮</span>
        <span style={{color: TS.ink, fontWeight: 700, letterSpacing: "0.32em", flexShrink: 0}}>TAPE//SHIFT</span>
        <span style={{color: TS.rule, flexShrink: 0}}>│</span>
        <span style={{flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"}}>{label}</span>
        <span style={{flex: 1}}></span>
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

type TsBtnProps = {
  children?: React.ReactNode; w?: number; h?: number;
  primary?: boolean; active?: boolean; onClick?: () => void;
};
function TsBtn({ children, w, h = 92, primary, active, onClick }: TsBtnProps) {
  return (
    <button onClick={onClick} style={{
      width: w ?? 110, height: h,
      background: primary ? TS.ember : (active ? TS.panelHi : TS.panel),
      color: primary ? "#1a0e08" : TS.ink,
      border: `1px solid ${primary ? TS.ember : TS.ruleHi}`,
      borderTop: `1px solid ${primary ? "#ffaa6a" : TS.ruleHi}`,
      borderBottom: `1px solid ${primary ? "#c54f10" : TS.rule}`,
      borderRadius: 14,
      cursor: "pointer", fontFamily: TS.mono, fontSize: 12, fontWeight: 700,
      letterSpacing: "0.18em", textTransform: "uppercase",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 4,
      transition: "all .1s",
      boxShadow: primary ? "0 6px 0 #c54f10, 0 14px 24px rgba(255,122,53,0.3)" : "0 4px 0 rgba(0,0,0,0.4)",
    }}>{children}</button>
  );
}

type ReelItem = { title: string; sub: string };
function ReelStrip({ items, activeIndex }: { items: ReelItem[]; activeIndex: number }) {
  const cardW = 240;
  const offset = -(activeIndex * (cardW + 14)) + (1232 - cardW) / 2;
  return (
    <div style={{position: "relative", height: 160, overflow: "hidden"}}>
      <div style={{position: "absolute", left: "50%", top: -6, bottom: -6, width: 2, background: TS.ember, zIndex: 2, boxShadow: `0 0 14px ${TS.ember}`}}/>
      <div style={{position: "absolute", left: "50%", top: -12, marginLeft: -10, width: 20, height: 8, background: TS.ember, clipPath: "polygon(0 0,100% 0,50% 100%)"}}/>
      <div style={{display: "flex", gap: 14, transform: `translateX(${offset}px)`, transition: "transform .35s cubic-bezier(.4,1.4,.5,1)"}}>
        {items.map((it, i) => {
          const active = i === activeIndex;
          const c = TS.ember;
          return (
            <div key={i} style={{
              width: cardW, flex: `0 0 ${cardW}px`, height: 160,
              background: active ? TS.panelHi : TS.panel,
              border: `1px solid ${active ? c : TS.ruleHi}`,
              borderRadius: 14, padding: "14px 16px",
              opacity: active ? 1 : 0.55,
              transform: active ? "scale(1.0)" : "scale(0.92)",
              transition: "all .25s",
              display: "flex", flexDirection: "column", justifyContent: "space-between",
              position: "relative", overflow: "hidden",
            }}>
              <div style={{position: "absolute", left: 14, right: 14, top: "50%",
                height: 18, opacity: active ? 0.6 : 0.25,
                background: `repeating-linear-gradient(0deg, transparent 0 1px, ${c} 1px 2px, transparent 2px 4px)`}}/>
              <div style={{position: "relative", display: "flex", justifyContent: "space-between", alignItems: "center", fontFamily: TS.mono, fontSize: 10, letterSpacing: "0.22em", color: c}}>
                <span>{String(i + 1).padStart(2, "0")}</span>
                <span>{active ? "▶ NOW" : "○"}</span>
              </div>
              <div style={{position: "relative"}}>
                <div style={{fontFamily: TS.font, fontWeight: 700, fontSize: 18, lineHeight: 1.1, letterSpacing: "-0.01em",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis"}}>
                  {it.title}
                </div>
                <div style={{fontFamily: TS.mono, fontSize: 11, color: TS.ink2, marginTop: 4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis"}}>
                  {it.sub}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TapeSignal({ height = 120, playing = true }: { height?: number; playing?: boolean }) {
  const t = useTicker(60);
  const spec = useSpectrum();
  const N = 220;
  return (
    <svg width="100%" viewBox={`0 0 ${N} ${height}`} preserveAspectRatio="none" style={{height, display: "block"}}>
      <line x1="0" x2={N} y1={height / 2} y2={height / 2} stroke={TS.rule} strokeWidth="1"/>
      {Array.from({length: N}).map((_, i) => {
        const bin = Math.min(63, Math.floor((i / N) * 64));
        // Reflect symmetric ±v above and below the centre line for tape feel.
        const v = (i % 2 === 0 ? 1 : -1) * spec.peaks[bin];
        void t; void vu; void playing;
        const h = Math.abs(v) * height * 0.85 + 1;
        return <rect key={i} x={i + 0.4} y={height / 2 - (v > 0 ? h : 0)} width={0.7} height={h}
          fill={v > 0.35 ? TS.ember : (v > 0 ? TS.lime : TS.cyan)}
          opacity={0.55 + Math.abs(v) * 0.9}/>;
      })}
    </svg>
  );
}

export type TapeshiftAudioProps = {
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

export function TapeshiftAudio({ track, state, elapsed, shuffle, repeat, chrome, onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek }: TapeshiftAudioProps & { chrome?: ChromeApi; onSeek?: (sec: number) => void }) {
  const playing = state === "playing";
  const tr = track ?? { title: "—", artist: "—", album: "—", len: 0, time: "0:00" };
  const len = tr.len > 0 ? tr.len : 1;
  const pct = Math.min(1, elapsed / len);
  // Reel uses the demo TRACKS as visual queue context. Active card: 3 (mid).
  const reelItems: ReelItem[] = TRACKS.map(d => ({ title: d.title, sub: `${d.artist} · ${d.time}` }));
  const idx = 3;
  const tsSpec = useSpectrum();
  void useTicker;

  return (
    <TsChrome label={playing ? "01 · NOW PLAYING" : "01 · PAUSED"} chrome={chrome}>
      <div style={{padding: "22px 24px 0", display: "grid", gridTemplateColumns: "1fr 360px", gap: 24}}>
        <div>
          <div style={{fontFamily: TS.mono, fontSize: 11, letterSpacing: "0.28em", color: TS.ember, marginBottom: 8}}>
            ▶ NOW PLAYING · LOCAL
          </div>
          <div style={{
            fontFamily: TS.font, fontSize: 54, fontWeight: 700, letterSpacing: "-0.03em", lineHeight: 1,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {tr.title}
          </div>
          <div style={{
            fontSize: 20, color: TS.ink2, marginTop: 8,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            <span style={{color: TS.ink}}>{tr.artist}</span>
            <span style={{margin: "0 10px", color: TS.rule}}>—</span>
            <em>{tr.album || "—"}</em>
          </div>
        </div>
        <div style={{background: TS.panel, border: `1px solid ${TS.rule}`, borderRadius: 14, padding: "14px 16px"}}>
          <div style={{fontFamily: TS.mono, fontSize: 10, letterSpacing: "0.22em", color: TS.ink2, marginBottom: 10}}>
            LEVEL · L / R
          </div>
          {[1, 2].map(s => {
            const v = s === 1 ? tsSpec.rmsL : tsSpec.rmsR;
            const segs = 28;
            const fill = Math.round(v * segs);
            return (
              <div key={s} style={{display: "flex", alignItems: "center", gap: 8, marginBottom: 6}}>
                <span style={{fontFamily: TS.mono, fontSize: 11, width: 14, color: TS.ink2}}>{s === 1 ? "L" : "R"}</span>
                <div style={{flex: 1, display: "flex", gap: 2, height: 14}}>
                  {Array.from({length: segs}).map((_, i) => {
                    const c = i < segs * 0.6 ? TS.lime : i < segs * 0.85 ? TS.ember : TS.red;
                    return <div key={i} style={{flex: 1, background: i < fill ? c : "rgba(255,255,255,0.04)"}}/>;
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{padding: "22px 0", borderTop: `1px solid ${TS.rule}`, marginTop: 18, background: `linear-gradient(180deg, ${TS.panel}, transparent 80%)`}}>
        <div style={{padding: "0 24px", fontFamily: TS.mono, fontSize: 10, letterSpacing: "0.28em", color: TS.ink2, marginBottom: 10, display: "flex", justifyContent: "space-between"}}>
          <span>◀ SIDE A · QUEUE ▶</span>
          <span style={{color: TS.ember}}>{tr.time}</span>
        </div>
        <ReelStrip items={reelItems} activeIndex={idx}/>
      </div>

      <div style={{padding: "0 24px 8px", marginTop: 14}}>
        <SeekableBar value={pct} lengthSec={len} onSeek={onSeek}>
          <div style={{position: "relative"}}>
            <TapeSignal height={70} playing={playing}/>
            <div style={{position: "absolute", left: `${pct * 100}%`, top: -2, bottom: -2, width: 2, background: TS.ink, boxShadow: `0 0 8px ${TS.ink}`, transform: "translateX(-50%)"}}/>
          </div>
        </SeekableBar>
        <div style={{display: "flex", justifyContent: "space-between", marginTop: 6, fontFamily: TS.mono, fontSize: 11, color: TS.ink2}}>
          <span style={{color: TS.ember, fontVariantNumeric: "tabular-nums"}}>{mmss(elapsed)}</span>
          <span style={{letterSpacing: "0.22em"}}>POSITION</span>
          <span style={{fontVariantNumeric: "tabular-nums"}}>−{mmss(Math.max(0, len - elapsed))}</span>
        </div>
      </div>

      <div style={{position: "absolute", left: 24, right: 24, bottom: 18, display: "flex", gap: 10, alignItems: "center"}}>
        <TsBtn w={104} h={88} onClick={onPrev}>
          <Icon name="prev" size={28} stroke={TS.ink}/>REW
        </TsBtn>
        <TsBtn w={180} h={88} primary onClick={onToggle}>
          <Icon name={playing ? "pause" : "play"} size={36} stroke="#1a0e08"/>
          {playing ? "PAUSE" : "PLAY"}
        </TsBtn>
        <TsBtn w={104} h={88} onClick={onNext}>
          <Icon name="next" size={28} stroke={TS.ink}/>FFW
        </TsBtn>
        <TsBtn w={88} h={88} active={shuffle} onClick={onToggleShuffle}><Icon name="shuffle" size={22} stroke={TS.ink}/></TsBtn>
        <TsBtn w={88} h={88} active={repeat} onClick={onToggleRepeat}><Icon name="repeat" size={22} stroke={TS.ink}/></TsBtn>
        <div style={{flex: 1}}></div>
        <TsBtn w={88} h={88}><Icon name="queue" size={22} stroke={TS.ink}/></TsBtn>
        <TsBtn w={88} h={88}><Icon name="search" size={22} stroke={TS.ink}/></TsBtn>
        <TsBtn w={120} h={88}>VOL · {/* live volume display */}<span style={{color: TS.ember}}>62</span></TsBtn>
      </div>
    </TsChrome>
  );
}
