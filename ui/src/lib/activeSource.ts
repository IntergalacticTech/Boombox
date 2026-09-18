import { useEffect, useRef, useState } from "react";

/** Power/standby state, added to /api/state by boombox-state's PowerManager.
 * Optional on purpose: an older server (or one that's down) simply doesn't
 * report it, and the UI must then behave exactly as it always did — awake. */
export type PowerState = {
  state: "awake" | "asleep";
  since: number;
  poweroff_at: number | null;
};

export type ActiveSource = {
  source: string | null;          // raw MPRIS player id (e.g. "ShairportSync") or null
  label: string | null;           // friendly label ("AirPlay", "Spotify", "Bluetooth")
  status: "playing" | "paused" | "stopped";
  track: { title?: string | null; artist?: string | null; album?: string | null } | null;
  volume: number | null;
  position_ms: number;
  length_ms: number;
  ts: number;
  power?: PowerState;
};

const EMPTY: ActiveSource = {
  source: null,
  label: null,
  status: "stopped",
  track: null,
  volume: null,
  position_ms: 0,
  length_ms: 0,
  ts: 0,
};

/**
 * Polls `/api/state` for the active non-Mopidy MPRIS player (AirPlay, Spotify
 * Connect, BT phone). The boombox UI uses this to override the now-playing
 * display when an external source is currently playing.
 */
export function useActiveSource(intervalMs = 1000): ActiveSource {
  const [state, setState] = useState<ActiveSource>(EMPTY);
  const aborted = useRef(false);

  useEffect(() => {
    aborted.current = false;
    const tick = async () => {
      try {
        const res = await fetch("/api/state", { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as ActiveSource;
        if (!aborted.current) setState(data);
      } catch {
        // network/transient — ignore; next tick will try again
      }
    };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      aborted.current = true;
      clearInterval(id);
    };
  }, [intervalMs]);

  return state;
}

/** True only when the server explicitly says the box is asleep. A missing
 * `power` key (old server, or /api/state unreachable) reads as awake so the
 * kiosk can never strand itself behind a black SleepScreen. */
export function isAsleep(s: ActiveSource): boolean {
  return s.power?.state === "asleep";
}

/** True if a non-Mopidy source is currently the active player. */
export function isExternalActive(s: ActiveSource): boolean {
  return Boolean(s.source) && (s.status === "playing" || s.status === "paused");
}

/**
 * POST /api/control/<action> — routes a transport action to the active
 * MPRIS player. Use only when isExternalActive(); otherwise call Mopidy
 * directly (its API is richer).
 */
export async function controlExternal(
  action: "play" | "pause" | "toggle" | "next" | "previous" | "stop"
): Promise<void> {
  try {
    await fetch(`/api/control/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    // best-effort; UI optimism is fine for transport
  }
}
