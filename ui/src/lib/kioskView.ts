import { useEffect } from "react";

/** What the kiosk screen shows, as remotes care about it: "home" is the
 * input picker; "player" is everything else (a skin, a drawer, the
 * Jellyfin page the kiosk navigates to for a movie). */
export type KioskView = "home" | "player";

export const KIOSK_VIEW_URL = "/api/remote/kiosk/view";

/** boombox-remote forgets a "home" report after 30 s without a refresh
 * (so leaving the SPA for Jellyfin can't strand the knob on Home); keep
 * comfortably inside that. */
export const KIOSK_VIEW_HEARTBEAT_MS = 10_000;

export function postKioskView(view: KioskView): void {
  fetch(KIOSK_VIEW_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ view }),
    keepalive: true,
  }).catch(() => { /* boombox-remote offline; remotes default to "player" */ });
}

/**
 * Report the kiosk's view to boombox-remote so the rotary knob (and other
 * remotes) can show "Home" while the input picker is up: on mount, on every
 * change, on a heartbeat, and "player" when the page goes away (the kiosk
 * navigating to Jellyfin for a movie).
 */
export function useReportKioskView(view: KioskView): void {
  useEffect(() => {
    postKioskView(view);
    const id = setInterval(() => postKioskView(view), KIOSK_VIEW_HEARTBEAT_MS);
    return () => clearInterval(id);
  }, [view]);

  useEffect(() => {
    const onHide = () => {
      const body = JSON.stringify({ view: "player" satisfies KioskView });
      try {
        if (navigator.sendBeacon?.(KIOSK_VIEW_URL, body)) return;
      } catch { /* fall through to fetch */ }
      postKioskView("player");
    };
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, []);
}
