// PairOverlay — full-screen modal showing a one-time PIN for pairing a
// wireless remote. On mount it POSTs /api/remote/pair/start to mint a PIN;
// the user types that PIN on a CYD (or any wireless-remote firmware), which
// POSTs to /api/remote/pair to redeem it for an auth token. PIN is
// single-use and expires after ~120s.

import { useEffect, useState } from "react";

type PairStartResponse = {
  ok: boolean;
  pin?: string;
  expires_at?: number;
  error?: string;
};

type Props = { onClose: () => void };

export function PairOverlay({ onClose }: Props) {
  const [pin, setPin] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [now, setNow] = useState<number>(Date.now() / 1000);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/remote/pair/start", { method: "POST" });
        const data: PairStartResponse = await r.json();
        if (cancelled) return;
        if (!r.ok || !data.ok || !data.pin) {
          setError(data.error || `HTTP ${r.status}`);
          return;
        }
        setPin(data.pin);
        setExpiresAt(data.expires_at ?? null);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const remaining = expiresAt != null
    ? Math.max(0, Math.ceil(expiresAt - now))
    : null;

  useEffect(() => {
    if (remaining === 0) {
      const id = setTimeout(onClose, 800);
      return () => clearTimeout(id);
    }
  }, [remaining, onClose]);

  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.88)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9000,
      }}
    >
      <div style={{
        background: "#16161a",
        color: "#fff",
        padding: "40px 56px",
        borderRadius: 16,
        textAlign: "center",
        minWidth: 360,
        maxWidth: "90%",
        border: "1px solid rgba(255,255,255,0.08)",
      }}>
        <div style={{
          fontSize: 13,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          opacity: 0.7,
          marginBottom: 18,
        }}>
          Pair wireless remote
        </div>

        {pin && !error && (
          <>
            <div style={{
              fontFamily: "'JetBrains Mono', ui-monospace, monospace",
              fontSize: 64,
              letterSpacing: "0.12em",
              color: "#4fc3f7",
              padding: "12px 0 4px 0",
              fontWeight: 700,
            }}>
              {pin}
            </div>
            <div style={{
              fontSize: 14,
              opacity: 0.7,
              margin: "12px 0 8px 0",
            }}>
              Enter this PIN on the remote.
            </div>
            {remaining != null && (
              <div style={{
                fontSize: 12,
                opacity: 0.5,
                margin: "0 0 24px 0",
              }}>
                Expires in {remaining}s
              </div>
            )}
          </>
        )}

        {error && (
          <div style={{ margin: "16px 0 24px 0", color: "#f48fb1" }}>
            Couldn't start pairing: {error}
          </div>
        )}

        {!pin && !error && (
          <div style={{ margin: "24px 0", opacity: 0.6 }}>Loading…</div>
        )}

        <button
          onClick={onClose}
          style={{
            padding: "12px 32px",
            background: "#4fc3f7",
            color: "#000",
            border: 0,
            borderRadius: 999,
            fontSize: 13,
            fontWeight: 700,
            letterSpacing: "0.10em",
            textTransform: "uppercase",
            cursor: "pointer",
          }}
        >
          Done
        </button>
      </div>
    </div>
  );
}
