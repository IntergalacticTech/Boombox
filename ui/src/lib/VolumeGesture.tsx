// VolumeGesture — invisible right-edge drag area for system-wide volume.
//
// Why this lives outside the per-skin volume bars: each skin renders its own
// VOL display, but those are decorative and not consistently sized for touch.
// A single global gesture region (right-edge swipe) gives a reliable,
// skin-agnostic volume control. Pulls/pushes /api/volume which talks to
// PipeWire's default sink — the change is system-wide, audible across
// Mopidy / AirPlay / Spotify / Bluetooth without per-source plumbing.

import { useEffect, useRef, useState } from "react";

const POLL_INTERVAL_MS = 4000;
const RIGHT_GUTTER_WIDTH_PX = 64;
const PILL_FADE_MS = 1100;

type Vol = { value: number; muted: boolean };

async function getVolume(): Promise<Vol | null> {
  try {
    const r = await fetch("/api/volume", { cache: "no-store" });
    if (!r.ok) return null;
    const j = await r.json();
    return { value: typeof j.volume === "number" ? j.volume : 0, muted: !!j.muted };
  } catch {
    return null;
  }
}

async function setVolume(v: number): Promise<void> {
  try {
    await fetch("/api/volume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ volume: v }),
    });
  } catch {
    // optimistic update; next poll reconciles
  }
}

export function VolumeGesture() {
  const [vol, setVol] = useState<number>(0.5);
  const [showing, setShowing] = useState(false);
  const fadeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dragging = useRef(false);

  // Initial fetch + low-frequency reconcile.
  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      const v = await getVolume();
      if (!stopped && v && !dragging.current) setVol(v.value);
    };
    tick();
    const id = setInterval(tick, POLL_INTERVAL_MS);
    return () => { stopped = true; clearInterval(id); };
  }, []);

  const showPill = () => {
    setShowing(true);
    if (fadeTimer.current) clearTimeout(fadeTimer.current);
    fadeTimer.current = setTimeout(() => setShowing(false), PILL_FADE_MS);
  };

  const yToVolume = (clientY: number) => {
    // Top of screen = max volume, bottom = 0. Range capped at 1.0 even though
    // wpctl can boost to 1.5; safer default for the touchscreen.
    const h = window.innerHeight;
    const t = 1 - clientY / h;
    return Math.max(0, Math.min(1, t));
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.clientX < window.innerWidth - RIGHT_GUTTER_WIDTH_PX) return;
    // Prevent the SkinPicker's document-level long-press handler from also
    // firing on this gutter touch (the picker uses a 700ms hold).
    e.stopPropagation();
    dragging.current = true;
    (e.target as Element).setPointerCapture(e.pointerId);
    const v = yToVolume(e.clientY);
    setVol(v);
    setVolume(v);
    showPill();
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    e.stopPropagation();
    const v = yToVolume(e.clientY);
    setVol(v);
    setVolume(v);
    showPill();
  };

  const endDrag = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    dragging.current = false;
    try { (e.target as Element).releasePointerCapture(e.pointerId); } catch { /* noop */ }
  };

  const pct = Math.round(vol * 100);

  return (
    <>
      {/* Invisible touch region: the right 64px of the viewport */}
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          width: RIGHT_GUTTER_WIDTH_PX,
          height: "100%",
          zIndex: 700,
          touchAction: "none",
          background: "transparent",
        }}
      />
      {/* Floating pill: shows current % during/right after drag */}
      <div
        style={{
          position: "fixed",
          right: 12,
          top: "50%",
          transform: `translateY(-50%) scale(${showing ? 1 : 0.85})`,
          opacity: showing ? 1 : 0,
          transition: "opacity .25s ease, transform .25s ease",
          pointerEvents: "none",
          zIndex: 750,
          background: "rgba(0,0,0,0.78)",
          color: "#fff",
          border: "1px solid rgba(255,255,255,0.18)",
          borderRadius: 14,
          padding: "10px 8px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 8,
          backdropFilter: "blur(8px)",
        }}
      >
        <div style={{
          width: 10,
          height: 180,
          borderRadius: 5,
          background: "rgba(255,255,255,0.12)",
          position: "relative",
          overflow: "hidden",
        }}>
          <div style={{
            position: "absolute",
            left: 0, right: 0, bottom: 0,
            height: `${pct}%`,
            background: "linear-gradient(180deg, #5be7ff, #b794ff)",
            transition: "height .12s",
          }}/>
        </div>
        <div style={{
          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
          fontSize: 12,
          fontVariantNumeric: "tabular-nums",
          letterSpacing: "0.08em",
        }}>
          {pct}
        </div>
      </div>
    </>
  );
}
