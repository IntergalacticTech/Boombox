// sleepTimer — global countdown that stops Mopidy at zero.
//
// The timer is persisted in localStorage as a unix-millis "fires-at" value
// so a kiosk reload mid-countdown picks up where it left off (no surprise
// silence after refreshing). A single ticker (driven by useSleepTimer) is
// shared across the app — multiple subscribers see consistent values.

import { useEffect, useState } from "react";

const KEY = "boombox.sleep.firesAt";

let _firesAt: number | null = readPersisted();
const _subs = new Set<(remainingSec: number | null) => void>();
let _interval: ReturnType<typeof setInterval> | null = null;

function readPersisted(): number | null {
  try {
    const v = localStorage.getItem(KEY);
    if (!v) return null;
    const n = Number(v);
    if (!Number.isFinite(n) || n <= Date.now()) {
      localStorage.removeItem(KEY);
      return null;
    }
    return n;
  } catch {
    return null;
  }
}

function persist() {
  try {
    if (_firesAt) localStorage.setItem(KEY, String(_firesAt));
    else localStorage.removeItem(KEY);
  } catch { /* ignore */ }
}

function publish() {
  const remaining = _firesAt ? Math.max(0, Math.round((_firesAt - Date.now()) / 1000)) : null;
  for (const s of _subs) s(remaining);
}

const FADE_DURATION_MS = 8000;
const FADE_STEPS = 24;

async function fireSleep() {
  _firesAt = null;
  persist();
  publish();
  // Smooth fade-out: read current volume, ramp it down to 0 over ~8 s, stop
  // playback, then restore the original level so next session isn't silent.
  let originalVolume: number | null = null;
  try {
    const r = await fetch("/api/volume", { cache: "no-store" });
    if (r.ok) {
      const j = await r.json();
      if (typeof j.volume === "number") originalVolume = j.volume;
    }
  } catch { /* fall through to abrupt stop */ }

  if (originalVolume != null && originalVolume > 0.01) {
    for (let i = 1; i <= FADE_STEPS; i++) {
      const f = 1 - (i / FADE_STEPS);
      try {
        await fetch("/api/volume", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ volume: originalVolume * f }),
        });
      } catch { break; }
      await new Promise(r => setTimeout(r, FADE_DURATION_MS / FADE_STEPS));
    }
  }
  try {
    await fetch("/mopidy/rpc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "core.playback.stop" }),
    });
  } catch { /* ignore */ }
  // Restore original volume so the next play session isn't silent.
  if (originalVolume != null) {
    try {
      await fetch("/api/volume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ volume: originalVolume }),
      });
    } catch { /* ignore */ }
  }
}

function ensureTicker() {
  if (_interval) return;
  _interval = setInterval(() => {
    if (!_firesAt) {
      if (_interval) { clearInterval(_interval); _interval = null; }
      return;
    }
    if (Date.now() >= _firesAt) {
      void fireSleep();
      return;
    }
    publish();
  }, 1000);
}

export function setSleepMinutes(minutes: number | null) {
  if (minutes == null || minutes <= 0) {
    _firesAt = null;
  } else {
    _firesAt = Date.now() + minutes * 60_000;
  }
  persist();
  ensureTicker();
  publish();
}

/** Returns remaining seconds, or null when no sleep timer is set. */
export function useSleepTimer(): number | null {
  const [remaining, setRemaining] = useState<number | null>(
    _firesAt ? Math.max(0, Math.round((_firesAt - Date.now()) / 1000)) : null,
  );

  useEffect(() => {
    const sub = (s: number | null) => setRemaining(s);
    _subs.add(sub);
    ensureTicker();
    return () => { _subs.delete(sub); };
  }, []);

  return remaining;
}
