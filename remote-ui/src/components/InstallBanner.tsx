import { useEffect, useState } from "react";

const DISMISS_KEY = "boombox.remote.install_dismissed_at";
const DISMISS_TTL_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

// minimal shape of the beforeinstallprompt event (not in lib.dom.d.ts)
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

function isStandalone(): boolean {
  if (window.matchMedia?.("(display-mode: standalone)").matches) return true;
  return Boolean((navigator as { standalone?: boolean }).standalone);
}

function isIOS(): boolean {
  const ua = navigator.userAgent;
  return /iPhone|iPad|iPod/.test(ua) && !/CriOS|FxiOS/.test(ua);
}

function wasDismissedRecently(): boolean {
  const at = Number(localStorage.getItem(DISMISS_KEY) || "0");
  if (!at) return false;
  return Date.now() - at < DISMISS_TTL_MS;
}

/** Suggests adding the PWA to the home screen. Android/Chromium gets the
 *  native install flow via beforeinstallprompt; iOS Safari shows a small
 *  text hint (Apple gives no API for the share-sheet prompt). The user
 *  can dismiss; we suppress for 30 days afterwards. */
export function InstallBanner() {
  const [evt, setEvt] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(wasDismissedRecently());
  const [showIos, setShowIos] = useState(false);

  useEffect(() => {
    if (isStandalone() || dismissed) return;
    if (isIOS()) {
      setShowIos(true);
      return;
    }
    const onPrompt = (e: Event) => {
      e.preventDefault();
      setEvt(e as BeforeInstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, [dismissed]);

  const dismiss = () => {
    localStorage.setItem(DISMISS_KEY, String(Date.now()));
    setDismissed(true);
    setShowIos(false);
    setEvt(null);
  };

  const install = async () => {
    if (!evt) return;
    await evt.prompt();
    const choice = await evt.userChoice;
    setEvt(null);
    if (choice.outcome === "dismissed") dismiss();
  };

  if (dismissed || isStandalone()) return null;
  if (!evt && !showIos) return null;

  return (
    <div role="region" aria-label="Install"
         style={{
           position: "fixed", top: 12, left: 12, right: 60, zIndex: 18,
           padding: "10px 12px", borderRadius: 12,
           background: "var(--panel)", border: "1px solid var(--rule)",
           display: "flex", alignItems: "center", gap: 10, fontSize: 12,
         }}>
      <span style={{ flex: 1, color: "var(--ink2)" }}>
        {evt
          ? "Install the Boombox Remote on your phone for full-screen access."
          : "Add to Home Screen via Share → Add to Home Screen for a full-screen remote."}
      </span>
      {evt && (
        <button type="button" onClick={install} style={{
          padding: "6px 12px", borderRadius: 8, border: 0,
          background: "var(--accent)", color: "var(--bg)",
          fontSize: 12, fontWeight: 600, cursor: "pointer",
        }}>Install</button>
      )}
      <button type="button" onClick={dismiss} aria-label="Dismiss" style={{
        background: "transparent", border: 0, color: "var(--ink2)",
        fontSize: 18, cursor: "pointer", lineHeight: 1, padding: "0 4px",
      }}>×</button>
    </div>
  );
}
