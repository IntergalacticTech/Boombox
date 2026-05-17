// RfidBindOverlay — pops when an unbound RFID tap is detected.
// Polls /api/rfid/recent every 2 s; when a new UID appears, prompts
// the user to pick something from the Home Library to bind it to.
//
// Bind flow:
//   1. Card tapped (unbound) → backend exposes uid via /api/rfid/recent
//   2. Overlay polls, sees new uid → shows "New card detected"
//   3. User taps "Bind to album..." → opens LibraryDrawer in bind mode
//   4. LibraryDrawer dispatches `boombox:rfid-bind-target` with kind+id
//   5. Overlay POSTs /api/rfid/bind and closes
//
// Dismissal is per-UID until the recent_ttl on the backend expires
// (default 30 s) — taps on the same card while the overlay is closed
// will re-trigger it.

import { useEffect, useRef, useState } from "react";
import { bind, getRecent, type BindingKind } from "../lib/rfidApi";

type Phase = "idle" | "prompting" | "picking" | "binding" | "done" | "error";

export function RfidBindOverlay() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [uid, setUid] = useState<string>("");
  const [msg, setMsg] = useState<string | null>(null);
  const dismissed = useRef<Set<string>>(new Set());

  // Poll /api/rfid/recent every 2 s. Cheap: a single small JSON read.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await getRecent();
        if (cancelled) return;
        if (!r.uid) return;
        if (dismissed.current.has(r.uid)) return;
        if (phase !== "idle") return;
        setUid(r.uid);
        setPhase("prompting");
      } catch { /* boombox-rfid offline — quiet */ }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [phase]);

  // When the LibraryDrawer is in bind mode and the user taps an item,
  // it dispatches this event with {kind, id, label}. We finish the bind.
  useEffect(() => {
    const handler = async (e: Event) => {
      if (phase !== "picking") return;
      const detail = (e as CustomEvent).detail as
        { kind: BindingKind; id: string; label: string };
      setPhase("binding"); setMsg(null);
      try {
        await bind(uid, detail.kind, detail.id, detail.label);
        setMsg(`Bound to ${detail.label}`);
        setPhase("done");
        setTimeout(() => close(), 1800);
      } catch (err) {
        setMsg(err instanceof Error ? err.message : String(err));
        setPhase("error");
      }
    };
    window.addEventListener("boombox:rfid-bind-target", handler as EventListener);
    return () => window.removeEventListener("boombox:rfid-bind-target", handler as EventListener);
  }, [phase, uid]);

  const close = () => {
    dismissed.current.add(uid);
    setPhase("idle"); setUid(""); setMsg(null);
  };

  const openLibraryToBind = () => {
    setPhase("picking");
    // The LibraryDrawer listens for this event — opens itself in "bind mode"
    // so the next tap on an album/artist/playlist fires
    // boombox:rfid-bind-target instead of playing.
    window.dispatchEvent(new CustomEvent("boombox:rfid-bind-start", { detail: { uid } }));
  };

  if (phase === "idle") return null;

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
        <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>
          {phase === "done" ? "Card bound" : "New card detected"}
        </div>
        <div style={{ fontSize: 13, color: "rgba(255,255,255,0.7)", marginBottom: 14,
                      fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.04em" }}>
          UID · {uid}
        </div>

        {phase === "prompting" && (
          <>
            <div style={{ fontSize: 15, marginBottom: 18 }}>
              Tap this card to play whatever you bind it to. Pick something
              from your Home Library now.
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button onClick={openLibraryToBind} style={btnPrimary}>
                BIND TO ALBUM…
              </button>
              <button onClick={close} style={btnSecondary}>
                NOT NOW
              </button>
            </div>
          </>
        )}

        {phase === "picking" && (
          <div style={{ fontSize: 15 }}>
            Pick an album, artist, or playlist in the Home Library.
            <br/><br/>
            <button onClick={close} style={btnSecondary}>CANCEL</button>
          </div>
        )}

        {phase === "binding" && (
          <div style={{ fontSize: 15 }}>Binding…</div>
        )}

        {phase === "done" && (
          <div style={{ fontSize: 15, color: "#9bf2c0" }}>✓ {msg}</div>
        )}

        {phase === "error" && (
          <>
            <div style={{ fontSize: 15, color: "#ff7a35", marginBottom: 12 }}>
              ✗ {msg}
            </div>
            <button onClick={close} style={btnSecondary}>DISMISS</button>
          </>
        )}
      </div>
    </div>
  );
}

const btnPrimary = {
  padding: "12px 18px", minHeight: 44,
  background: "#5be7ff", color: "#000",
  border: "none", borderRadius: 999,
  fontWeight: 700, fontSize: 13, letterSpacing: "0.08em",
  cursor: "pointer",
} as const;
const btnSecondary = {
  padding: "12px 18px", minHeight: 44,
  background: "rgba(255,255,255,0.08)", color: "#fff",
  border: "1px solid rgba(255,255,255,0.18)", borderRadius: 999,
  fontWeight: 700, fontSize: 13, letterSpacing: "0.08em",
  cursor: "pointer",
} as const;
