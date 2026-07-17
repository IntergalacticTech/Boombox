// First-run gate for the kiosk. On a fresh device the setup wizard lives at
// /setup/; until it's finished, the kiosk should show the wizard instead of
// the player. We only redirect on the kiosk itself (localhost) — the
// authenticated LAN web UI on :8090 is never bounced into setup.
//
// Returns true when it has initiated a redirect, so main.tsx can skip
// rendering the player and avoid a flash of the wrong UI.

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);

export async function redirectToSetupIfIncomplete(): Promise<boolean> {
  if (!LOCAL_HOSTS.has(window.location.hostname)) return false;
  // Already in the wizard — never loop.
  if (window.location.pathname.startsWith("/setup")) return false;

  // On a cold boot the kiosk browser can load before boombox-setup has
  // finished starting. A single failed fetch must NOT drop a fresh device
  // onto the player (it would silently skip setup), so retry a few times
  // before giving up. Once we get any answer we act on it immediately.
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      const r = await fetch("/api/setup/status", { cache: "no-store" });
      if (r.ok) {
        const s = await r.json();
        if (s && s.complete === false) {
          window.location.replace("/setup/");
          return true;
        }
        return false; // definitively complete — show the player
      }
    } catch {
      // service not up yet — fall through to the backoff and retry
    }
    await new Promise((res) => setTimeout(res, 500));
  }
  // Still no answer after ~2.5s — fail open to the player rather than trap
  // the kiosk on a blank screen. An older device without the route lands here.
  return false;
}
