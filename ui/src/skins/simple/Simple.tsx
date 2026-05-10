// SIMPLE — adapted from skins/simple/source.jsx
// Clean dark streaming-app vibe with terminal accents.
import React from "react";
import { Icon, useTicker, vu, mmss, TRACKS } from "../../lib/shared";
import { useSpectrum } from "../../lib/spectrum";
import { SeekableBar } from "../../lib/SeekableBar";
import { AlbumThumb } from "../../lib/AlbumThumb";
import type { ChromeApi } from "../../lib/skinRegistry";
import type { Track, PlayState } from "../../lib/types";

const SMP = {
  bg:        "#07060c",
  panel:     "#100d1c",
  panelHi:   "#181530",
  rule:      "rgba(255,255,255,0.08)",
  ruleHi:    "rgba(255,255,255,0.16)",
  ink:       "#f3f1ff",
  ink2:      "#9892b8",
  ink3:      "#5e597a",
  violet:    "#8b5cf6",
  blue:      "#3b82f6",
  glow:      "#a78bfa",
  cyan:      "#5be7ff",
  amber:     "#ffb84d",
  font:      "'Inter', system-ui, -apple-system, sans-serif",
  mono:      "'JetBrains Mono', monospace",
};

function AsciiSeg({ value, width = 16, color = SMP.cyan }: { value: number; width?: number; color?: string }) {
  const fill = Math.round(value * width);
  const cells: string[] = [];
  for (let i = 0; i < width; i++) {
    if (i < fill - 1)        cells.push("█");
    else if (i === fill - 1) cells.push("▓");
    else if (i === fill)     cells.push("░");
    else                     cells.push("·");
  }
  return (
    <span style={{fontFamily: SMP.mono, fontSize: 11, letterSpacing: "0.04em"}}>
      {cells.map((ch, i) => (
        <span key={i} style={{color: i < fill ? color : SMP.ink3}}>{ch}</span>
      ))}
    </span>
  );
}

function SmpFrame({ children, active = "home", chrome }: { children: React.ReactNode; active?: string; chrome?: ChromeApi }) {
  const t = useTicker(500);
  // Sidebar nav: items that have a chrome action are clickable; others are
  // decorative for now (Video / etc.).
  const navItems: { id: string; label: string; icon: string; k: string; onClick?: () => void; badge?: string }[] = [
    {id: "home",     label: "Now Playing", icon: "play",    k: "01"},
    {id: "sources",  label: chrome ? `Sources · ${chrome.sourceLabel}` : "Sources", icon: "cast", k: "02", onClick: chrome?.onOpenSource},
    {id: "queue",    label: chrome ? `Queue · ${chrome.queueCount}` : "Queue", icon: "queue", k: "03", onClick: chrome?.onOpenQueue},
    {id: "skin",     label: chrome ? `Skin · ${chrome.skinName}` : "Skin", icon: "search", k: "04", onClick: chrome?.onOpenSkinPicker},
    {id: "settings", label: "Settings",    icon: "search",  k: "05", onClick: chrome?.onOpenSettings},
  ];
  return (
    <div style={{
      width: 1280, height: 800, background: SMP.bg, color: SMP.ink, fontFamily: SMP.font,
      position: "relative", overflow: "hidden", display: "flex",
    }}>
      <div style={{position: "absolute", inset: 0, pointerEvents: "none", zIndex: 50,
        backgroundImage: "repeating-linear-gradient(0deg, rgba(255,255,255,0.018) 0 1px, transparent 1px 3px)"}}/>

      <div style={{width: 240, background: SMP.panel, borderRight: `1px solid ${SMP.rule}`,
        display: "flex", flexDirection: "column", padding: "22px 16px", position: "relative"}}>
        <div style={{display: "flex", alignItems: "center", gap: 10, marginBottom: 8}}>
          <div style={{width: 32, height: 32, borderRadius: 8,
            background: `linear-gradient(135deg, ${SMP.violet}, ${SMP.blue})`,
            boxShadow: `0 0 18px ${SMP.violet}40`}}/>
          <div>
            <div style={{fontSize: 17, fontWeight: 700, letterSpacing: "-0.01em"}}>Boombox</div>
            <div style={{fontFamily: SMP.mono, fontSize: 9, color: SMP.cyan, letterSpacing: "0.18em"}}>
              v0.4.1 · {t % 2 ? "ONLINE" : "ONLINE_"}
            </div>
          </div>
        </div>

        <div style={{fontFamily: SMP.mono, fontSize: 10, color: SMP.ink3, letterSpacing: "0.22em",
          margin: "22px 4px 8px"}}>// NAV</div>

        <div style={{display: "flex", flexDirection: "column", gap: 2}}>
          {navItems.map(item => {
            const on = item.id === active;
            const clickable = !!item.onClick;
            return (
              <button
                key={item.id}
                onClick={item.onClick}
                disabled={!clickable}
                style={{
                  display: "flex", alignItems: "center", gap: 12, padding: "13px 12px",
                  borderRadius: 10,
                  background: on ? "rgba(139,92,246,0.15)" : "transparent",
                  color: on ? SMP.ink : (clickable ? SMP.ink2 : SMP.ink3),
                  cursor: clickable ? "pointer" : "default",
                  fontSize: 13, fontWeight: on ? 600 : 500, position: "relative",
                  borderLeft: on ? `2px solid ${SMP.cyan}` : "2px solid transparent",
                  border: "none",
                  textAlign: "left",
                  fontFamily: "inherit",
                  width: "100%",
                  minHeight: 48,
                }}
              >
                <Icon name={item.icon} size={18} stroke={on ? SMP.glow : SMP.ink2} sw={1.8}/>
                <span style={{
                  flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>{item.label}</span>
                <span style={{fontFamily: SMP.mono, fontSize: 10, color: on ? SMP.cyan : SMP.ink3, letterSpacing: "0.12em"}}>
                  {item.k}
                </span>
              </button>
            );
          })}
        </div>

        <div style={{marginTop: "auto", padding: "14px 10px", borderTop: `1px solid ${SMP.rule}`,
          fontFamily: SMP.mono, fontSize: 10, color: SMP.ink3, letterSpacing: "0.08em"}}>
          <div style={{display: "flex", justifyContent: "space-between", color: SMP.ink2, marginBottom: 6}}>
            <span>[ DAC ]</span>
            <span style={{color: SMP.cyan}}>● 48k/24b</span>
          </div>
          <div style={{display: "flex", justifyContent: "space-between", marginBottom: 4}}>
            <span>[ CPU ]</span><span>{12 + (t % 4)}%</span>
          </div>
          <div style={{display: "flex", justifyContent: "space-between"}}>
            <span>[ NET ]</span><span style={{color: SMP.cyan}}>−52dBm</span>
          </div>
        </div>
      </div>
      <div style={{flex: 1, position: "relative", overflow: "hidden"}}>{children}</div>
    </div>
  );
}

function SmpCircleBtn({ children, size = 56, primary, active, onClick }: { children?: React.ReactNode; size?: number; primary?: boolean; active?: boolean; onClick?: () => void }) {
  return (
    <button onClick={onClick} style={{
      width: size, height: size, borderRadius: "50%",
      background: primary ? "#fff" : (active ? "rgba(167,139,250,0.35)" : "rgba(255,255,255,0.08)"),
      color: primary ? SMP.bg : SMP.ink,
      border: "none", cursor: "pointer",
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      transition: "all .12s",
      boxShadow: primary ? `0 0 32px rgba(167,139,250,0.45), 0 0 0 1px rgba(255,255,255,0.4) inset` : (active ? "0 0 0 1px rgba(167,139,250,0.6) inset" : "none"),
    }}>{children}</button>
  );
}

function SmpStat({ label, value, color = SMP.ink2 }: { label: string; value: string; color?: string }) {
  return (
    <div style={{display: "flex", alignItems: "center", gap: 8, padding: "6px 12px",
      background: "rgba(0,0,0,0.4)", border: `1px solid ${SMP.rule}`, borderRadius: 999,
      fontFamily: SMP.mono, fontSize: 11, letterSpacing: "0.14em"}}>
      <span style={{color: SMP.ink3}}>[{label}]</span>
      <span style={{color}}>{value}</span>
    </div>
  );
}

export type SimpleAudioProps = {
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

export function SimpleAudio({ track, state, elapsed, volume, shuffle, repeat, chrome, onToggle, onNext, onPrev, onToggleShuffle, onToggleRepeat, onSeek }: SimpleAudioProps & { chrome?: ChromeApi; onSeek?: (sec: number) => void }) {
  const playing = state === "playing";
  const tr = track ?? { uri: "", title: "—", artist: "—", album: "—", len: 0, time: "0:00", hue: 200 };
  const len = tr.len > 0 ? tr.len : 1;
  const pct = Math.min(1, elapsed / len);
  const t = useTicker(80);
  const spec = useSpectrum();
  const lvl = spec.rmsL;
  const rvl = spec.rmsR;
  void t; void vu;
  const volPct = (volume ?? 62) / 100;

  return (
    <SmpFrame active="home" chrome={chrome}>
      <div style={{position: "absolute", top: 0, left: 0, right: 0, height: 380,
        background: `linear-gradient(180deg, rgba(139,92,246,0.28) 0%, rgba(59,130,246,0.10) 40%, transparent 100%)`,
        pointerEvents: "none"}}/>
      <div style={{position: "relative", height: "100%", display: "flex", flexDirection: "column"}}>
        <div style={{padding: "18px 36px 14px", display: "flex", alignItems: "center", gap: 10,
          borderBottom: `1px solid ${SMP.rule}`, fontFamily: SMP.mono}}>
          <div style={{display: "flex", gap: 6}}>
            <button style={{width: 34, height: 34, borderRadius: "50%", background: "rgba(0,0,0,0.5)", border: `1px solid ${SMP.rule}`, color: SMP.ink, cursor: "pointer", fontSize: 15}}>‹</button>
            <button style={{width: 34, height: 34, borderRadius: "50%", background: "rgba(0,0,0,0.5)", border: `1px solid ${SMP.rule}`, color: SMP.ink, cursor: "pointer", fontSize: 15}}>›</button>
          </div>
          <SmpStat label="SRC"  value="LOCAL"            color={SMP.glow}/>
          <SmpStat label="OUT"  value="DAC pcm5122"      color={SMP.cyan}/>
          <SmpStat label="FMT"  value="MP3 320 · 48k"    color={SMP.ink2}/>
          <span style={{flex: 1}}></span>
          <SmpStat label="WIFI" value="−52dBm"           color={SMP.cyan}/>
          <SmpStat label="UTC"  value={t % 2 ? "23:41:08" : "23:41:08_"} color={SMP.amber}/>
        </div>

        <div style={{padding: "22px 36px 22px", display: "flex", gap: 28, alignItems: "flex-end"}}>
          <div style={{
            width: 220, height: 220, borderRadius: 14,
            position: "relative",
            boxShadow: `0 24px 60px rgba(0,0,0,0.6), 0 0 0 1px ${SMP.ruleHi}`,
            overflow: "hidden",
            flexShrink: 0,
          }}>
            <AlbumThumb
              artist={tr.artist}
              album={tr.album}
              track={tr.title}
              seed={tr.uri}
              size={220}
              radius={14}
            />
            <div style={{position: "absolute", top: 10, left: 12, fontFamily: SMP.mono, fontSize: 10,
              color: "rgba(255,255,255,0.85)", letterSpacing: "0.18em",
              padding: "3px 8px", background: "rgba(0,0,0,0.5)", borderRadius: 4,
              backdropFilter: "blur(4px)"}}>
              [ NOW ]
            </div>
          </div>
          <div style={{flex: 1, paddingBottom: 8, minWidth: 0}}>
            <div style={{display: "flex", alignItems: "center", gap: 10, marginBottom: 14}}>
              <span style={{fontFamily: SMP.mono, fontSize: 11, color: SMP.cyan, letterSpacing: "0.22em"}}>
                {playing ? "▶ NOW PLAYING" : "❚❚ PAUSED"}
              </span>
              <span style={{fontFamily: SMP.mono, fontSize: 11, color: SMP.ink3, letterSpacing: "0.18em"}}>
                · LOCAL · DAC ·
              </span>
            </div>
            <div style={{fontSize: 60, fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 0.95, marginBottom: 14,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis"}}>
              {tr.title}<span style={{color: SMP.cyan}}>_</span>
            </div>
            <div style={{fontSize: 15, color: SMP.ink2, display: "flex", alignItems: "center", gap: 8, marginBottom: 14, fontFamily: SMP.mono}}>
              <span style={{fontWeight: 600, color: SMP.ink}}>{tr.artist}</span>
              <span style={{color: SMP.ink3}}>//</span>
              <span>{tr.album || "—"}</span>
              <span style={{color: SMP.ink3}}>//</span>
              <span>{tr.time}</span>
            </div>
            <div style={{display: "flex", alignItems: "center", gap: 14, fontFamily: SMP.mono}}>
              <span style={{fontSize: 11, color: SMP.ink3, letterSpacing: "0.18em"}}>L</span>
              <AsciiSeg value={lvl} width={28} color={SMP.cyan}/>
              <span style={{fontSize: 11, color: SMP.ink3, letterSpacing: "0.18em", marginLeft: 8}}>R</span>
              <AsciiSeg value={rvl} width={28} color={SMP.glow}/>
            </div>
          </div>
        </div>

        <div style={{padding: "0 36px", flex: 1, minHeight: 0, display: "flex", flexDirection: "column"}}>
          <div style={{display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12}}>
            <div style={{display: "flex", alignItems: "baseline", gap: 10}}>
              <span style={{fontFamily: SMP.mono, fontSize: 11, color: SMP.cyan, letterSpacing: "0.22em"}}>// QUEUE</span>
              <span style={{fontSize: 18, fontWeight: 700, letterSpacing: "-0.01em"}}>Up Next</span>
            </div>
            <div style={{fontFamily: SMP.mono, fontSize: 11, color: SMP.ink2, letterSpacing: "0.14em"}}>
              [ DEMO QUEUE ]
            </div>
          </div>
          <div style={{flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", gap: 2}}>
            {TRACKS.slice(0, 6).map((d, i) => {
              const active = i === 0;
              return (
                <div key={i} style={{
                  display: "grid", gridTemplateColumns: "32px 36px 1fr 1fr 80px 60px", gap: 14,
                  padding: "9px 14px", borderRadius: 8, alignItems: "center",
                  background: active ? "rgba(139,92,246,0.10)" : "transparent",
                  fontSize: 14,
                }}>
                  <span style={{color: active ? SMP.cyan : SMP.ink3, fontFamily: SMP.mono, fontSize: 12, letterSpacing: "0.08em"}}>
                    {active ? "▶" : String(i + 1).padStart(2, "0")}
                  </span>
                  <div style={{width: 36, height: 36, borderRadius: 6,
                    background: `linear-gradient(135deg, hsl(${d.hue}, 70%, 55%), hsl(${(d.hue + 40) % 360}, 60%, 35%))`}}/>
                  <div style={{minWidth: 0}}>
                    <div style={{fontWeight: 600, color: active ? SMP.glow : SMP.ink, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis"}}>{d.title}</div>
                    <div style={{fontSize: 12, color: SMP.ink2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis"}}>{d.artist}</div>
                  </div>
                  <div style={{color: SMP.ink2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontFamily: SMP.mono, fontSize: 13}}>{d.album}</div>
                  <div style={{fontFamily: SMP.mono, fontSize: 11, color: SMP.ink3, letterSpacing: "0.12em"}}>
                    {["MP3·320", "FLAC", "FLAC", "WAV", "MP3·320", "FLAC"][i]}
                  </div>
                  <div style={{color: active ? SMP.cyan : SMP.ink2, fontFamily: SMP.mono, fontSize: 13, textAlign: "right", fontVariantNumeric: "tabular-nums"}}>{d.time}</div>
                </div>
              );
            })}
          </div>
        </div>

        <div style={{padding: "14px 36px", borderTop: `1px solid ${SMP.rule}`,
          background: "rgba(7,6,12,0.85)", backdropFilter: "blur(12px)",
          display: "grid", gridTemplateColumns: "260px 1fr 260px", gap: 24, alignItems: "center"}}>
          <div style={{display: "flex", alignItems: "center", gap: 12, minWidth: 0}}>
            <div style={{width: 44, height: 44, borderRadius: 6,
              background: `linear-gradient(135deg, hsl(${tr.hue}, 70%, 55%), hsl(${(tr.hue + 60) % 360}, 60%, 35%))`, flexShrink: 0}}/>
            <div style={{minWidth: 0}}>
              <div style={{fontSize: 13, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis"}}>{tr.title}</div>
              <div style={{fontSize: 11, color: SMP.ink2, fontFamily: SMP.mono, letterSpacing: "0.06em"}}>{tr.artist}</div>
            </div>
          </div>

          <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 8}}>
            <div style={{display: "flex", alignItems: "center", gap: 12}}>
              <SmpCircleBtn size={44} active={shuffle} onClick={onToggleShuffle}><Icon name="shuffle" size={18}/></SmpCircleBtn>
              <SmpCircleBtn size={48} onClick={onPrev}><Icon name="prev" size={22}/></SmpCircleBtn>
              <SmpCircleBtn size={64} primary onClick={onToggle}>
                <Icon name={playing ? "pause" : "play"} size={26} stroke={SMP.bg}/>
              </SmpCircleBtn>
              <SmpCircleBtn size={48} onClick={onNext}><Icon name="next" size={22}/></SmpCircleBtn>
              <SmpCircleBtn size={44} active={repeat} onClick={onToggleRepeat}><Icon name="repeat" size={18}/></SmpCircleBtn>
            </div>
            <div style={{display: "flex", alignItems: "center", gap: 10, width: "100%", maxWidth: 480}}>
              <span style={{fontFamily: SMP.mono, fontSize: 11, color: SMP.cyan, fontVariantNumeric: "tabular-nums", letterSpacing: "0.06em"}}>{mmss(elapsed)}</span>
              <SeekableBar value={pct} lengthSec={len} onSeek={onSeek} style={{flex: 1}}>
                <div style={{height: 4, background: "rgba(255,255,255,0.12)", borderRadius: 2, position: "relative"}}>
                  <div style={{height: "100%", width: `${pct * 100}%`,
                    background: `linear-gradient(90deg, ${SMP.violet}, ${SMP.blue})`, borderRadius: 2}}/>
                  <div style={{position: "absolute", left: `${pct * 100}%`, top: -5, width: 14, height: 14, borderRadius: "50%", background: "#fff", transform: "translateX(-50%)"}}/>
                </div>
              </SeekableBar>
              <span style={{fontFamily: SMP.mono, fontSize: 11, color: SMP.ink2, fontVariantNumeric: "tabular-nums", letterSpacing: "0.06em"}}>−{mmss(Math.max(0, len - elapsed))}</span>
            </div>
          </div>

          <div style={{display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 10}}>
            <span style={{fontFamily: SMP.mono, fontSize: 10, color: SMP.ink3, letterSpacing: "0.18em"}}>VOL</span>
            <Icon name="vol" size={18} stroke={SMP.ink2}/>
            <div style={{flex: 1, maxWidth: 140, height: 4, background: "rgba(255,255,255,0.12)", borderRadius: 2, position: "relative"}}>
              <div style={{height: "100%", width: `${volPct * 100}%`, background: SMP.glow, borderRadius: 2}}/>
              <div style={{position: "absolute", left: `${volPct * 100}%`, top: -5, width: 14, height: 14, borderRadius: "50%", background: "#fff", transform: "translateX(-50%)"}}/>
            </div>
            <span style={{fontFamily: SMP.mono, fontSize: 11, color: SMP.cyan, letterSpacing: "0.06em"}}>{volume ?? "—"}</span>
          </div>
        </div>
      </div>
    </SmpFrame>
  );
}
