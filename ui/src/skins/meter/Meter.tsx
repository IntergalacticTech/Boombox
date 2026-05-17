// METER — adapted from skins/meter/source.jsx
// Analog VU/gauge worship: cream paper + ink black + safety-orange peak.
import React from "react";
import { Icon, useTicker, vu, mmss } from "../../lib/shared";
import { useSpectrum } from "../../lib/spectrum";
import { ChromeSourceBtn, ChromeQueueBtn, ChromeSkinBtn, ChromeSettingsBtn } from "../../lib/ChromeButtons";
import { SyncIndicator } from "../../lib/SyncIndicator";
import { SeekableBar } from "../../lib/SeekableBar";
import type { ChromeApi } from "../../lib/skinRegistry";
import type { Track, PlayState } from "../../lib/types";

const MTR = {
  bg:       "#ece6d8",
  paper:    "#f4efe2",
  ink:      "#16140e",
  ink2:     "#5a5345",
  rule:     "#cdc5b1",
  ruleHi:   "#1c1a13",
  amber:    "#e26a1f",
  red:      "#c93a2a",
  green:    "#3a7a4a",
  cream:    "#fbf6e8",
  font:     "'Space Grotesk', -apple-system, system-ui, sans-serif",
  mono:     "'JetBrains Mono', monospace",
};

function MtrChrome({ children, label = "01 · NOW PLAYING", chrome }: { children: React.ReactNode; label?: string; chrome?: ChromeApi }) {
  // Meter chrome: cream paper, ink black borders, amber-on-cream pills.
  const chromeTheme = {
    bg: MTR.cream,
    fg: MTR.ink,
    border: MTR.ruleHi,
    font: MTR.mono,
    mono: MTR.mono,
    height: 60,
    radius: 6,
    padding: "0 14px",
  };
  return (
    <div style={{
      width: 1280, height: 800, background: MTR.bg, color: MTR.ink, fontFamily: MTR.font,
      position: "relative", overflow: "hidden",
    }}>
      <div style={{
        height: 96, padding: "0 24px", display: "flex", alignItems: "center", gap: 14,
        borderBottom: `1px solid ${MTR.ruleHi}`, background: MTR.paper,
        fontFamily: MTR.mono, fontSize: 12, letterSpacing: "0.18em", textTransform: "uppercase",
      }}>
        <span style={{fontWeight: 700, fontSize: 14, letterSpacing: "0.32em", flexShrink: 0}}>METER · BOOMBOX</span>
        <span style={{color: MTR.ink2, flexShrink: 0}}>—</span>
        <span style={{color: MTR.ink2, flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"}}>{label}</span>
        <span style={{flex: 1}}></span>
        {chrome && (
          <>
            <ChromeSourceBtn chrome={chrome} theme={chromeTheme}/>
            <SyncIndicator />
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

type GaugeProps = { value?: number; label: string; peak?: string; size?: number; danger?: number };
function NeedleGauge({ value = 0.6, label, peak, size = 320, danger = 0.85 }: GaugeProps) {
  const angle = -120 + value * 240;
  const ticks = Array.from({length: 21});
  return (
    <div style={{
      width: size, height: size * 0.78, position: "relative",
      background: MTR.cream, border: `1px solid ${MTR.ruleHi}`,
      padding: "14px 16px 0", display: "flex", flexDirection: "column",
    }}>
      <div style={{display: "flex", justifyContent: "space-between", alignItems: "baseline", fontFamily: MTR.mono, fontSize: 11, letterSpacing: "0.18em"}}>
        <span style={{fontWeight: 700}}>{label}</span>
        <span style={{color: MTR.ink2}}>VU · dB</span>
      </div>
      <svg viewBox="-100 -90 200 110" style={{width: "100%", flex: 1, marginTop: 4}}>
        <path d="M -78 0 A 78 78 0 0 1 78 0" fill="none" stroke={MTR.ink} strokeWidth="0.8"/>
        <path d="M 49 -60.7 A 78 78 0 0 1 78 0" fill="none" stroke={MTR.red} strokeWidth="3"/>
        {ticks.map((_, i) => {
          const t = i / 20;
          const a = (-120 + t * 240) * Math.PI / 180;
          const r1 = 78, r2 = (i % 5 === 0) ? 64 : 71;
          const x1 = Math.sin(a) * r1, y1 = -Math.cos(a) * r1;
          const x2 = Math.sin(a) * r2, y2 = -Math.cos(a) * r2;
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={t > 0.85 ? MTR.red : MTR.ink} strokeWidth={i % 5 === 0 ? 1.4 : 0.6}/>;
        })}
        {[
          {t: 0,    v: "−∞"}, {t: 0.25, v: "−20"}, {t: 0.5, v: "−10"}, {t: 0.7, v: "−3"}, {t: 0.85, v: "0"}, {t: 1, v: "+3"},
        ].map(({t, v}) => {
          const a = (-120 + t * 240) * Math.PI / 180;
          const r = 56;
          const x = Math.sin(a) * r, y = -Math.cos(a) * r;
          return <text key={v} x={x} y={y + 3} fill={t > 0.85 ? MTR.red : MTR.ink} fontSize="6.5" fontFamily={MTR.mono} textAnchor="middle">{v}</text>;
        })}
        <g style={{transform: `rotate(${angle}deg)`, transformOrigin: "0 0", transition: "transform 0.18s ease-out"}}>
          <line x1="0" y1="6" x2="0" y2="-72" stroke={value > danger ? MTR.red : MTR.ruleHi} strokeWidth="1.8" strokeLinecap="round"/>
          <circle cx="0" cy="0" r="4" fill={MTR.ruleHi}/>
        </g>
      </svg>
      <div style={{position: "absolute", left: 0, right: 0, bottom: 8, textAlign: "center", fontFamily: MTR.mono, fontSize: 11, letterSpacing: "0.16em", color: MTR.ink2}}>
        peak <span style={{color: value > danger ? MTR.red : MTR.ink, fontWeight: 700}}>{peak ?? `−${(20 - value * 22).toFixed(1)} dB`}</span>
      </div>
    </div>
  );
}

type MtrButtonProps = { children?: React.ReactNode; w?: number; h?: number; active?: boolean; onClick?: () => void; big?: boolean };
function MtrButton({ children, w = 120, h = 88, active, onClick, big }: MtrButtonProps) {
  return (
    <button onClick={onClick} style={{
      width: w, height: h, border: `1.5px solid ${MTR.ruleHi}`,
      background: active ? MTR.ink : MTR.cream,
      color: active ? MTR.cream : MTR.ink,
      fontFamily: MTR.mono, fontSize: big ? 15 : 12, fontWeight: 700,
      letterSpacing: "0.18em", textTransform: "uppercase", cursor: "pointer",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 6,
      boxShadow: active ? `2px 2px 0 ${MTR.amber}` : `2px 2px 0 ${MTR.ruleHi}`,
      transition: "all .08s",
    }}>{children}</button>
  );
}

export type MeterAudioProps = {
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

export function MeterAudio({ track, state, elapsed, volume, shuffle, repeat, chrome, onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek }: MeterAudioProps & { chrome?: ChromeApi; onSeek?: (sec: number) => void }) {
  const playing = state === "playing";
  const t = useTicker(80);
  const tr = track ?? { title: "—", artist: "—", album: "—", len: 0, time: "0:00" };
  const len = tr.len > 0 ? tr.len : 1;
  const pct = Math.min(1, elapsed / len);
  const spec = useSpectrum();
  const lpk = spec.rmsL;
  const rpk = spec.rmsR;
  void t; void vu;
  const volPct = (volume ?? 62) / 100;

  return (
    <MtrChrome label={playing ? "01 · AUDIO · PLAY" : "01 · AUDIO · PAUSE"} chrome={chrome}>
      <div style={{padding: "24px 28px", height: "calc(100% - 96px)", display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 24}}>
        <div style={{display: "flex", flexDirection: "column", gap: 18}}>
          <div style={{display: "flex", gap: 14}}>
            <NeedleGauge value={0.5 + lpk * 0.4} label="LEFT" size={320} peak={`−${(8 - lpk * 8).toFixed(1)} dB`}/>
            <NeedleGauge value={0.5 + rpk * 0.4} label="RIGHT" size={320} peak={`−${(8 - rpk * 8).toFixed(1)} dB`}/>
          </div>

          <div style={{background: MTR.cream, border: `1px solid ${MTR.ruleHi}`, padding: "16px 20px"}}>
            <div style={{display: "flex", justifyContent: "space-between", fontFamily: MTR.mono, fontSize: 11, letterSpacing: "0.18em", marginBottom: 14}}>
              <span style={{fontWeight: 700}}>EQ · 3 BAND</span>
              <span style={{color: MTR.ink2}}>POST</span>
            </div>
            <div style={{display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 30}}>
              {[{l: "BASS", v: 0.7, hz: "60Hz"}, {l: "MID", v: 0.45, hz: "1kHz"}, {l: "TREB", v: 0.6, hz: "8kHz"}].map((b, i) => (
                <div key={i}>
                  <div style={{display: "flex", justifyContent: "space-between", fontFamily: MTR.mono, fontSize: 11, marginBottom: 6}}>
                    <span style={{fontWeight: 700}}>{b.l}</span>
                    <span style={{color: MTR.ink2}}>{b.hz}</span>
                  </div>
                  <div style={{height: 14, background: MTR.bg, border: `1px solid ${MTR.ruleHi}`, position: "relative"}}>
                    <div style={{position: "absolute", left: 0, top: 0, bottom: 0, width: `${b.v * 100}%`, background: MTR.ink}}/>
                    <div style={{position: "absolute", left: "50%", top: -2, bottom: -2, width: 1, background: MTR.amber}}/>
                  </div>
                  <div style={{fontFamily: MTR.mono, fontSize: 11, color: MTR.ink2, marginTop: 4, textAlign: "right"}}>
                    {b.v > 0.5 ? "+" : ""}{((b.v - 0.5) * 12).toFixed(1)} dB
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div style={{display: "flex", flexDirection: "column", gap: 18}}>
          <div style={{background: MTR.paper, border: `1px solid ${MTR.ruleHi}`, padding: "22px 24px"}}>
            <div style={{fontFamily: MTR.mono, fontSize: 11, letterSpacing: "0.22em", color: MTR.ink2, marginBottom: 8}}>
              NOW PLAYING · LOCAL
            </div>
            <div style={{
              fontSize: 34, fontWeight: 700, lineHeight: 1.05, letterSpacing: "-0.02em",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>
              {tr.title}
            </div>
            <div style={{
              fontSize: 18, color: MTR.ink2, marginTop: 6,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>
              {tr.artist} · <em style={{color: MTR.ink}}>{tr.album || "—"}</em>
            </div>

            <div style={{marginTop: 22, display: "flex", alignItems: "baseline", justifyContent: "space-between", borderTop: `1px solid ${MTR.rule}`, paddingTop: 18}}>
              <div>
                <div style={{fontFamily: MTR.mono, fontSize: 10, letterSpacing: "0.22em", color: MTR.ink2}}>ELAPSED</div>
                <div style={{fontFamily: MTR.mono, fontSize: 46, fontWeight: 700, lineHeight: 1, fontVariantNumeric: "tabular-nums"}}>
                  {mmss(elapsed)}
                </div>
              </div>
              <div style={{textAlign: "right"}}>
                <div style={{fontFamily: MTR.mono, fontSize: 10, letterSpacing: "0.22em", color: MTR.ink2}}>REMAIN</div>
                <div style={{fontFamily: MTR.mono, fontSize: 46, fontWeight: 700, lineHeight: 1, fontVariantNumeric: "tabular-nums", color: MTR.amber}}>
                  −{mmss(Math.max(0, len - elapsed))}
                </div>
              </div>
            </div>

            <SeekableBar value={pct} lengthSec={len} onSeek={onSeek} style={{marginTop: 14}}>
              <div style={{height: 6, background: MTR.bg, border: `1px solid ${MTR.ruleHi}`, position: "relative"}}>
                <div style={{position: "absolute", left: 0, top: 0, bottom: 0, width: `${pct * 100}%`, background: MTR.ink}}/>
              </div>
            </SeekableBar>
          </div>

          <div style={{display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10}}>
            <MtrButton h={96} onClick={onPrev}><Icon name="prev" size={26}/>PREV</MtrButton>
            <MtrButton h={96} big active={playing} onClick={onToggle}>
              <Icon name={playing ? "pause" : "play"} size={36} stroke={MTR.cream}/>
              {playing ? "PAUSE" : "PLAY"}
            </MtrButton>
            <MtrButton h={96} onClick={onNext}><Icon name="next" size={26}/>NEXT</MtrButton>
          </div>
          <div style={{display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8}}>
            <MtrButton h={68} active={shuffle} onClick={onToggleShuffle}><Icon name="shuffle" size={20}/></MtrButton>
            <MtrButton h={68} active={repeat} onClick={onToggleRepeat}><Icon name="repeat" size={20}/></MtrButton>
            <MtrButton h={68}><Icon name="queue" size={20}/></MtrButton>
            <MtrButton h={68}><Icon name="search" size={20}/></MtrButton>
          </div>

          <div style={{background: MTR.cream, border: `1px solid ${MTR.ruleHi}`, padding: "14px 18px"}}>
            <div style={{display: "flex", justifyContent: "space-between", fontFamily: MTR.mono, fontSize: 11, letterSpacing: "0.18em", marginBottom: 8}}>
              <span style={{fontWeight: 700}}>VOLUME</span>
              <span style={{color: MTR.amber}}>{volume == null ? "—" : `${volume}%`}</span>
            </div>
            <div style={{height: 12, background: MTR.bg, border: `1px solid ${MTR.ruleHi}`, position: "relative"}}>
              <div style={{position: "absolute", left: 0, top: 0, bottom: 0, width: `${volPct * 100}%`, background: `repeating-linear-gradient(90deg, ${MTR.ink} 0 6px, transparent 6px 8px)`}}/>
              <div style={{position: "absolute", left: `${volPct * 100}%`, top: -4, bottom: -4, width: 6, background: MTR.amber, border: `1px solid ${MTR.ruleHi}`, transform: "translateX(-50%)"}}/>
            </div>
          </div>
        </div>
      </div>
    </MtrChrome>
  );
}
