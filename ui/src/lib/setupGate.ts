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
  try {
    const r = await fetch("/api/setup/status", { cache: "no-store" });
    if (!r.ok) return false;
    const s = await r.json();
    if (s && s.complete === false) {
      window.location.replace("/setup/");
      return true;
    }
  } catch {
    // boombox-setup down or route absent (older device) — fail open to the
    // player rather than trapping the kiosk on a blank screen.
  }
  return false;
}
