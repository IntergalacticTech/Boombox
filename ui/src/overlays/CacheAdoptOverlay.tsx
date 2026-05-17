// CacheAdoptOverlay — modal that prompts the user to bless a fresh USB
// drive as the boombox offline cache.
//
// Trigger model: App.tsx polls /api/library/cache/candidates every 5 s
// and dispatches `boombox:cache-candidate` when it sees the first
// unadopted drive AND no cache is currently adopted. The overlay
// listens for that event so the polling logic stays in one place.
//
// Dismissal is per-mount-path: a "No" on /media/X suppresses the prompt
// for /media/X until the user replugs (path goes away then reappears).

import { useEffect, useState } from "react";
import { adoptCache } from "../lib/libraryApi";
import { refreshNow } from "../lib/homeLibrary";

type Candidate = {
  mount_path: string;
  label: string;
  free_bytes: number | null;
  total_bytes: number | null;
};

function fmtGB(bytes: number | null): string {
  if (!bytes) return "—";
  const gb = bytes / 1024 / 1024 / 1024;
  return gb >= 10 ? `${gb.toFixed(0)} GB` : `${gb.toFixed(1)} GB`;
}

export function CacheAdoptOverlay() {
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [busy, setBusy] = useState(false);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  useEffect(() => {
    const handler = (e: Event) => {
      const c = (e as CustomEvent).detail as Candidate;
      if (dismissed.has(c.mount_path)) return;
      setCandidate(c);
    };
    window.addEventListener("boombox:cache-candidate", handler as EventListener);
    return () => window.removeEventListener("boombox:cache-candidate", handler as EventListener);
  }, [dismissed]);

  if (!candidate) return null;

  const onYes = async () => {
    setBusy(true);
    try {
      await adoptCache(candidate.mount_path);
      await refreshNow();
      setCandidate(null);
    } catch { setCandidate(null); }
    finally { setBusy(false); }
  };
  const onNo = () => {
    setDismissed(s => { const next = new Set(s); next.add(candidate.mount_path); return next; });
    setCandidate(null);
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)", color: "white",
      display: "grid", placeItems: "center", zIndex: 9998, padding: 32,
    }}>
      <div style={{
        maxWidth: 560, background: "#0a0a0a",
        border: "1px solid rgba(255,255,255,0.14)", borderRadius: 14,
        padding: 24, textAlign: "left",
      }}>
        <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>New drive detected</div>
        <div style={{ fontSize: 14, color: "rgba(255,255,255,0.7)", marginBottom: 14,
                      fontFamily: "'JetBrains Mono', monospace" }}>
          {candidate.label} · Free: {fmtGB(candidate.free_bytes)}
        </div>
        <div style={{ fontSize: 15, marginBottom: 18 }}>
          Use this as the boombox offline cache? Existing files on the drive stay where they are.
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button
            disabled={busy}
            onClick={onYes}
            style={{
              padding: "12px 18px", minHeight: 44,
              background: "#5be7ff", color: "#000",
              border: "none", borderRadius: 999,
              fontWeight: 700, fontSize: 13, letterSpacing: "0.08em",
              cursor: "pointer", opacity: busy ? 0.6 : 1,
            }}
          >{busy ? "ADOPTING…" : "YES, USE FOR CACHE"}</button>
          <button
            disabled={busy}
            onClick={onNo}
            style={{
              padding: "12px 18px", minHeight: 44,
              background: "rgba(255,255,255,0.08)", color: "#fff",
              border: "1px solid rgba(255,255,255,0.18)", borderRadius: 999,
              fontWeight: 700, fontSize: 13, letterSpacing: "0.08em",
              cursor: "pointer",
            }}
          >NO, BROWSE AS MEDIA</button>
        </div>
      </div>
    </div>
  );
}
