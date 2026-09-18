// SleepScreen — what the kiosk shows while the box is asleep.
//
// The panel's backlight is off (boombox-state drives wlr-randr), so nothing
// here is normally visible; this layer exists so that the *first* touch after
// the screen comes back on wakes the box instead of pressing whatever button
// happened to be under the finger. It sits above every drawer and overlay and
// swallows the event.
//
// It never renders the awake UI's state and never fetches anything on a timer:
// App polls /api/state, and the server's answer is what unmounts this.

import { useEffect, useRef } from "react";

export function SleepScreen() {
  // A finger held on a resistive panel fires pointerdown + touchstart, and a
  // held GPIO key repeats. One POST is enough — the server is idempotent, but
  // there's no reason to hammer it while the wake sequence runs.
  const sent = useRef(false);

  const wake = () => {
    if (sent.current) return;
    sent.current = true;
    // Silent on failure: the poll decides whether we are still asleep, and if
    // the POST was lost the next touch (after the guard resets) tries again.
    fetch("/api/power/wake", { method: "POST" })
      .catch(() => { /* boombox-state down — nothing useful to show on a dark panel */ })
      .finally(() => { setTimeout(() => { sent.current = false; }, 1500); });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { e.preventDefault(); wake(); };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  return (
    <div
      data-testid="sleep-screen"
      aria-hidden="true"
      onPointerDown={(e) => { e.preventDefault(); e.stopPropagation(); wake(); }}
      onTouchStart={(e) => { e.stopPropagation(); wake(); }}
      onClick={(e) => { e.stopPropagation(); }}
      style={{
        position: "fixed",
        inset: 0,
        background: "#000",
        zIndex: 2147483647,   // above NowPlayingBar (9995) and every overlay
        touchAction: "none",
        cursor: "none",
      }}
    />
  );
}
