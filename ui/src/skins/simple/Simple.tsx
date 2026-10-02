// SIMPLE — adapted from skins/simple/source.jsx
// Clean dark streaming-app vibe with terminal accents.
import React from "react";
import { Icon, mmss } from "../../lib/shared";
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

/** Local wall-clock time as 24h HH:MM, refreshed every few seconds. */
function useClock(): string {
  const fmt = () => new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", hour12: false});
  const [now, setNow] = React.useState(fmt);
  React.useEffect(() => {
    const id = setInterval(() => setNow(fmt()), 5000);
    return () => clearInterval(id);
  }, []);
  return now;
}

/** Slide-in nav timing. Transform/opacity only, so the Pi's compositor does
 *  the work, and nothing animates once the menu has settled. */
const MENU_SLIDE_MS = 220;
/** Auto-close the menu after this long with no touches inside it. */
const MENU_IDLE_MS = 8000;
const MENU_W = 260;
/** Menu button: fixed upper-left, same spot open or closed. 72 design px
 *  ≈ 44 px on the 800×480 panel. */
const MENU_BTN = { left: 16, top: 8, size: 72 };
/** Left inset for the player's top row so its chips clear the menu button. */
const MENU_BTN_CLEARANCE = MENU_BTN.left + MENU_BTN.size + 24;

function SmpFrame({ children, active = "home", chrome }: { children: React.ReactNode; active?: string; chrome?: ChromeApi }) {
  // Always starts closed; the open state is deliberately not persisted.
  const [open, setOpen] = React.useState(false);
  const idleRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearIdle = React.useCallback(() => {
    if (idleRef.current !== null) { clearTimeout(idleRef.current); idleRef.current = null; }
  }, []);
  const armIdle = React.useCallback(() => {
    clearIdle();
    idleRef.current = setTimeout(() => { idleRef.current = null; setOpen(false); }, MENU_IDLE_MS);
  }, [clearIdle]);

  // The idle timer only exists while the menu is open.
  React.useEffect(() => {
    if (!open) { clearIdle(); return; }
    armIdle();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => { clearIdle(); window.removeEventListener("keydown", onKey); };
  }, [open, armIdle, clearIdle]);

  // Nav items: those with a chrome action run it; "Now Playing" is the
  // current view, so choosing it just closes the menu. Every choice closes.
  const navItems: { id: string; label: string; icon: string; k: string; onClick?: () => void; aria?: string }[] = [
    {id: "home",     label: "Now Playing", icon: "play",    k: "01", onClick: () => {}},
    {id: "gohome",   label: chrome ? `Home · ${chrome.sourceLabel}` : "Home", aria: "Home", icon: "home", k: "02", onClick: chrome?.onGoHome},
    {id: "library",  label: "Library",     icon: "search",  k: "03", onClick: chrome?.onOpenLibrary},
    {id: "queue",    label: chrome ? `Queue · ${chrome.queueCount}` : "Queue", icon: "queue", k: "04", onClick: chrome?.onOpenQueue},
    {id: "skin",     label: chrome ? `Skin · ${chrome.skinName}` : "Skin", icon: "eq", k: "05", onClick: chrome?.onOpenSkinPicker},
    {id: "settings", label: "Settings",    icon: "settings", k: "06", onClick: chrome?.onOpenSettings},
  ];
  const ease = "cubic-bezier(0.2, 0.8, 0.2, 1)";
  return (
    <div style={{
      width: 1280, height: 800, background: SMP.bg, color: SMP.ink, fontFamily: SMP.font,
      position: "relative", overflow: "hidden",
    }}>
      <div style={{position: "absolute", inset: 0, pointerEvents: "none", zIndex: 50,
        backgroundImage: "repeating-linear-gradient(0deg, rgba(255,255,255,0.018) 0 1px, transparent 1px 3px)"}}/>

      {/* Player content always spans the full width; the menu overlays it. */}
      <div style={{position: "absolute", inset: 0, overflow: "hidden"}}>{children}</div>

      {/* Scrim: fades in behind the open menu; tapping it closes the menu. */}
      <div
        data-testid="simple-menu-scrim"
        aria-hidden="true"
        onClick={() => setOpen(false)}
        style={{
          position: "absolute", inset: 0, zIndex: 60,
          background: "rgba(4,3,10,0.6)",
          opacity: open ? 1 : 0,
          pointerEvents: open ? "auto" : "none",
          transition: `opacity ${MENU_SLIDE_MS}ms ${ease}`,
        }}
      />

      <nav
        id="simple-nav"
        aria-label="Main menu"
        aria-hidden={!open}
        inert={!open}
        onPointerDown={armIdle}
        onTouchStart={armIdle}
        onKeyDown={armIdle}
        style={{
          position: "absolute", top: 0, bottom: 0, left: 0, width: MENU_W, zIndex: 70,
          background: SMP.panel, borderRight: `1px solid ${SMP.rule}`,
          boxShadow: open ? "12px 0 40px rgba(0,0,0,0.5)" : "none",
          display: "flex", flexDirection: "column", padding: "8px 16px 22px",
          transform: open ? "translateX(0)" : "translateX(-100%)",
          // Hidden after the slide-out finishes, so the closed menu isn't painted.
          visibility: open ? "visible" : "hidden",
          transition: open
            ? `transform ${MENU_SLIDE_MS}ms ${ease}, visibility 0s linear 0s`
            : `transform ${MENU_SLIDE_MS}ms ${ease}, visibility 0s linear ${MENU_SLIDE_MS}ms`,
        }}
      >
        {/* Logo sits beside the (separately rendered) menu button. */}
        <div style={{display: "flex", alignItems: "center", gap: 10, height: MENU_BTN.size,
          paddingLeft: MENU_BTN.left + MENU_BTN.size - 4, flexShrink: 0}}>
          <div style={{width: 28, height: 28, borderRadius: 8, flexShrink: 0,
            background: `linear-gradient(135deg, ${SMP.violet}, ${SMP.blue})`,
            boxShadow: `0 0 18px ${SMP.violet}40`}}/>
          <div style={{fontSize: 17, fontWeight: 700, letterSpacing: "-0.01em"}}>Boombox</div>
        </div>

        <div style={{fontFamily: SMP.mono, fontSize: 10, color: SMP.ink3, letterSpacing: "0.22em",
          margin: "22px 4px 8px"}}>// NAV</div>

        <div style={{display: "flex", flexDirection: "column", gap: 2}}>
          {navItems.map(item => {
            const on = item.id === active;
            const action = item.onClick;
            const clickable = !!action;
            return (
              <button
                key={item.id}
                onClick={action ? () => { action(); setOpen(false); } : undefined}
                disabled={!clickable}
                aria-label={item.aria ?? item.label}
                aria-current={on ? "page" : undefined}
                style={{
                  display: "flex", alignItems: "center", gap: 12, padding: "13px 12px",
                  borderRadius: 10,
                  background: on ? "rgba(139,92,246,0.15)" : "transparent",
                  color: on ? SMP.ink : (clickable ? SMP.ink2 : SMP.ink3),
                  cursor: clickable ? "pointer" : "default",
                  fontSize: 13, fontWeight: on ? 600 : 500, position: "relative",
                  border: "none",
                  borderLeft: on ? `2px solid ${SMP.cyan}` : "2px solid transparent",
                  textAlign: "left",
                  fontFamily: "inherit",
                  width: "100%",
                  minHeight: 64,
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
      </nav>

      {/* Menu toggle: same place and look whether the menu is open or closed. */}
      <button
        aria-label="Menu"
        aria-expanded={open}
        aria-controls="simple-nav"
        onClick={() => setOpen(o => !o)}
        style={{
          position: "absolute", left: MENU_BTN.left, top: MENU_BTN.top, zIndex: 80,
          width: MENU_BTN.size, height: MENU_BTN.size, borderRadius: 16,
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          background: open ? "rgba(139,92,246,0.22)" : "rgba(255,255,255,0.06)",
          border: `1px solid ${open ? "rgba(167,139,250,0.5)" : SMP.ruleHi}`,
          color: SMP.ink, cursor: "pointer", padding: 0,
          transition: `background-color ${MENU_SLIDE_MS}ms, border-color ${MENU_SLIDE_MS}ms`,
        }}
      >
        <Icon name="menu" size={28} stroke={open ? SMP.glow : SMP.ink} sw={2}/>
      </button>
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

function SmpStat({ label, value, color = SMP.ink2, minWidth }: { label: string; value: string; color?: string; minWidth?: number }) {
  return (
    <div style={{display: "flex", alignItems: "center", gap: 8, padding: "6px 12px",
      background: "rgba(0,0,0,0.4)", border: `1px solid ${SMP.rule}`, borderRadius: 999,
      fontFamily: SMP.mono, fontSize: 11, letterSpacing: "0.14em"}}>
      <span style={{color: SMP.ink3}}>[{label}]</span>
      <span style={{color, fontVariantNumeric: "tabular-nums", minWidth, textAlign: "right"}}>{value}</span>
    </div>
  );
}

function SmpPanelBtn({ children, icon, primary, onClick }: { children: React.ReactNode; icon: string; primary?: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      height: 72, padding: "0 24px", borderRadius: 999, flexShrink: 0,
      display: "inline-flex", alignItems: "center", gap: 10,
      background: primary ? `linear-gradient(135deg, ${SMP.violet}, ${SMP.blue})` : "rgba(255,255,255,0.08)",
      color: SMP.ink, border: `1px solid ${primary ? "transparent" : SMP.ruleHi}`,
      fontFamily: SMP.font, fontSize: 16, fontWeight: 600, cursor: "pointer",
    }}>
      <Icon name={icon} size={20} stroke={SMP.ink} sw={1.8}/>
      {children}
    </button>
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
  const spec = useSpectrum();
  const lvl = spec.rmsL;
  const rvl = spec.rmsR;
  const clock = useClock();
  const queueCount = chrome?.queueCount ?? 0;
  const volPct = (volume ?? 62) / 100;

  return (
    <SmpFrame active="home" chrome={chrome}>
      <div style={{position: "absolute", top: 0, left: 0, right: 0, height: 380,
        background: `linear-gradient(180deg, rgba(139,92,246,0.28) 0%, rgba(59,130,246,0.10) 40%, transparent 100%)`,
        pointerEvents: "none"}}/>
      <div style={{position: "relative", height: "100%", display: "flex", flexDirection: "column"}}>
        <div style={{padding: `0 36px 0 ${MENU_BTN_CLEARANCE}px`, minHeight: 88, display: "flex", alignItems: "center", gap: 10,
          borderBottom: `1px solid ${SMP.rule}`, fontFamily: SMP.mono}}>
          {chrome && <SmpStat label="SRC" value={chrome.sourceLabel} color={SMP.glow}/>}
          <span style={{flex: 1}}></span>
          {/* Fixed-width, tabular digits: the row must not shift as time ticks. */}
          <SmpStat label="TIME" value={clock} color={SMP.amber} minWidth={44}/>
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
              {chrome && (
                <span style={{fontFamily: SMP.mono, fontSize: 11, color: SMP.ink3, letterSpacing: "0.18em"}}>
                  · {chrome.sourceLabel}
                </span>
              )}
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
              [ {queueCount} IN QUEUE ]
            </div>
          </div>
          {/* The skin only gets the queue's length, not its tracks, so this
            * panel is a summary that hands off to the Queue / Library drawers
            * rather than a track list. */}
          <div style={{flex: 1, minHeight: 0, display: "flex", alignItems: "center", gap: 20,
            padding: "0 20px", marginBottom: 20, borderRadius: 12, background: "rgba(139,92,246,0.06)",
            border: `1px solid ${SMP.rule}`}}>
            <div style={{flex: 1, minWidth: 0}}>
              <div style={{fontSize: 22, fontWeight: 700, letterSpacing: "-0.01em"}}>
                {queueCount > 0
                  ? `${queueCount} ${queueCount === 1 ? "track" : "tracks"} in the queue`
                  : "Nothing queued"}
              </div>
              <div style={{fontFamily: SMP.mono, fontSize: 12, color: SMP.ink2, letterSpacing: "0.08em", marginTop: 6}}>
                {queueCount > 0 ? "Open the queue to see what's next" : "Browse the library to pick some music"}
              </div>
            </div>
            {chrome && queueCount > 0 && (
              <SmpPanelBtn onClick={chrome.onOpenQueue} icon="queue">Open queue</SmpPanelBtn>
            )}
            {chrome && (
              <SmpPanelBtn onClick={chrome.onOpenLibrary} icon="search" primary={queueCount === 0}>Browse library</SmpPanelBtn>
            )}
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
