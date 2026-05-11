// Boombox kiosk helper — content script.
//
// Adds a floating "← BOOMBOX" pill in the top-left of any page that isn't
// the boombox SPA itself, so the touchscreen has a one-tap way out of
// Jellyfin or any other detour the kiosk has wandered into.
//
// The boombox SPA lives at http://localhost/ (any path, no port). Anything
// else gets the pill. We deliberately don't tie the check to a specific
// detour — that way a future Watch source (a YouTube TV page, a Twitch
// stream, whatever) gets the same affordance for free.

(function () {
  const isBoomboxHome = () => {
    const u = window.location;
    if (u.hostname !== "localhost" && u.hostname !== "127.0.0.1") return false;
    // The boombox SPA listens on bare port 80 (or :5173 in dev). Anything
    // with a non-empty, non-80 port (Jellyfin: 8096, etc.) is a detour.
    const port = u.port || "80";
    return port === "80" || port === "5173";
  };

  const ensurePill = () => {
    if (document.getElementById("__boombox_return_pill")) return;
    const pill = document.createElement("div");
    pill.id = "__boombox_return_pill";
    pill.setAttribute("role", "button");
    pill.setAttribute("aria-label", "Return to boombox UI");
    pill.innerHTML = '<span class="arrow">←</span><span>BOOMBOX</span>';
    pill.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      // Hard navigation so the destination page reloads cleanly even from
      // a SPA that's hijacked history (Jellyfin does this aggressively).
      window.location.href = "http://localhost/";
    }, { passive: false });
    // Insert at the very end of <body> so it lands on top of late-mounted
    // overlays. body may not exist yet if document_idle fired oddly fast.
    (document.body || document.documentElement).appendChild(pill);
  };

  const removePill = () => {
    const p = document.getElementById("__boombox_return_pill");
    if (p) p.remove();
  };

  const sync = () => { isBoomboxHome() ? removePill() : ensurePill(); };

  sync();

  // SPAs (Jellyfin, etc.) rewrite history without firing 'load'. Re-check
  // on every navigation we can see.
  const wrap = (fn) => function () {
    const ret = fn.apply(this, arguments);
    queueMicrotask(sync);
    return ret;
  };
  history.pushState   = wrap(history.pushState);
  history.replaceState = wrap(history.replaceState);
  window.addEventListener("popstate", sync);
  window.addEventListener("hashchange", sync);

  // Belt and suspenders for sites that swap large DOM trees and might wipe
  // our pill node along the way.
  new MutationObserver(() => {
    if (!isBoomboxHome() && !document.getElementById("__boombox_return_pill")) {
      ensurePill();
    }
  }).observe(document.documentElement, { childList: true, subtree: true });

  // ------------------------------------------------------------------------
  // On-screen keyboard: ask boombox-state (via the service worker) to show
  // wvkbd when a text input gets focus, hide on blur.
  // ------------------------------------------------------------------------
  const TEXT_INPUT_TYPES = new Set([
    "", "text", "password", "search", "email", "tel", "url", "number",
  ]);

  function isTextLike(el) {
    if (!el || el.nodeType !== 1) return false;
    if (el.tagName === "TEXTAREA") return true;
    if (el.tagName === "INPUT") {
      return TEXT_INPUT_TYPES.has((el.type || "").toLowerCase());
    }
    return el.isContentEditable === true;
  }

  let oskRequested = false;
  function requestOSK(action) {
    if (action === "show" && oskRequested) return;
    if (action === "hide" && !oskRequested) return;
    oskRequested = (action === "show");
    try {
      chrome.runtime.sendMessage({ type: "osk", action });
    } catch (e) {
      // Extension context invalidated (Chromium restart, etc.) — bail.
    }
  }

  document.addEventListener("focusin", (e) => {
    if (isTextLike(e.target)) requestOSK("show");
  }, true);

  document.addEventListener("focusout", () => {
    // Slight delay so a focus moving from one input to another doesn't
    // flicker the keyboard.
    setTimeout(() => {
      if (!isTextLike(document.activeElement)) requestOSK("hide");
    }, 80);
  }, true);

  // Also hide on page hide / navigation away — otherwise wvkbd may stay up
  // when the kiosk lands somewhere keyboard-less.
  window.addEventListener("pagehide", () => requestOSK("hide"));
})();
