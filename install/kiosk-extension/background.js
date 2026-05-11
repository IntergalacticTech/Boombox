// Boombox kiosk helper — background service worker.
//
// Lives only to forward messages from the content script to boombox-state's
// OSK endpoints. Doing the fetch here (rather than in the content script)
// sidesteps CORS: the host page (Jellyfin on :8096, the boombox SPA on :80,
// etc.) may have a strict CSP that would block a cross-origin fetch to
// localhost:80, but the service worker uses extension origin and the
// host_permissions declared in manifest.json.
//
// Coalesces rapid show/hide bursts (focus moving across inputs) so we don't
// hammer the endpoint or pump wvkbd into a flicker loop.

const OSK_BASE = "http://localhost/api/osk";

let pending = null;        // "show" | "hide" | null
let flushing = false;

async function flush() {
  if (flushing || !pending) return;
  flushing = true;
  try {
    while (pending) {
      const action = pending;
      pending = null;
      try {
        await fetch(`${OSK_BASE}/${action}`, { method: "POST" });
      } catch (e) {
        // boombox-state down or the route doesn't exist yet — silent.
      }
    }
  } finally {
    flushing = false;
  }
}

let debounceTimer = null;
function schedule(action) {
  pending = action;
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(flush, 50);
}

chrome.runtime.onMessage.addListener((msg) => {
  if (!msg || msg.type !== "osk") return;
  if (msg.action === "show" || msg.action === "hide") {
    schedule(msg.action);
  }
});
