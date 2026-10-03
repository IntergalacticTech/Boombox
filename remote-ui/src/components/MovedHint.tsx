import { useEffect, useState } from "react";

const SEEN_KEY = "boombox.moved_hint_seen";

function fromOldApp(): boolean {
  return new URLSearchParams(window.location.search).get("from") === "remote";
}

function seen(): boolean {
  try { return localStorage.getItem(SEEN_KEY) === "1"; } catch { return false; }
}

/** One-time hint for people arriving from the old /remote/ address (nginx
 *  redirects it to /?from=remote): the app lives at / now, so an old
 *  home-screen icon should be replaced. */
export function MovedHint() {
  const [show] = useState(() => fromOldApp() && !seen());
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!fromOldApp()) return;
    // Drop the marker so a reload or bookmark doesn't re-trigger it, and
    // remember we've shown it.
    window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    try { localStorage.setItem(SEEN_KEY, "1"); } catch { /* private mode */ }
  }, []);

  if (!show || dismissed) return null;
  return (
    <div role="region" aria-label="The app moved" style={{
      margin: 12, padding: "10px 12px", borderRadius: 12, fontSize: 13,
      background: "var(--panel)", border: "1px solid var(--accent)",
      display: "flex", alignItems: "center", gap: 10,
    }}>
      <span style={{ flex: 1, minWidth: 0 }}>
        The Boombox app now lives at <strong>{window.location.host}/</strong>. If you added
        the old remote to your home screen, remove it and add this page instead.
      </span>
      <button type="button" aria-label="Dismiss" onClick={() => setDismissed(true)} style={{
        background: "transparent", border: 0, color: "var(--ink2)", fontSize: 18,
        cursor: "pointer", lineHeight: 1,
      }}>×</button>
    </div>
  );
}
