import { useState } from "react";
import { redeemPin, savePairing } from "../lib/pairing";
import type { Pairing as PairingData } from "../lib/pairing";

const ERRORS: Record<string, string> = {
  bad_pin: "Incorrect PIN — check the boombox screen and try again.",
  no_active_pin: "That PIN expired. Generate a new one on the boombox.",
  remote_disabled: "Remote access is off — turn it on in the boombox's Settings.",
  unreachable: "Couldn't reach that boombox. Check the address and your WiFi.",
};

/** Address + PIN entry. Resolves a host into the LAN origin
 *  `http://<host>:8090`, redeems the PIN, persists the pairing, and hands
 *  it up via onPaired. */
export function Pairing({ onPaired }: { onPaired: (p: PairingData) => void }) {
  const [host, setHost] = useState("");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const normalizeBase = (h: string): string => {
    const trimmed = h.trim().replace(/\/$/, "");
    if (/^https?:\/\//.test(trimmed)) return trimmed;
    if (/:\d+$/.test(trimmed)) return `http://${trimmed}`;
    return `http://${trimmed}:8090`;
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const base = normalizeBase(host);
    const res = await redeemPin(base, pin.trim(), "phone");
    setBusy(false);
    if (res.ok) {
      const pairing: PairingData = { base, token: res.token, name: res.name };
      savePairing(pairing);
      onPaired(pairing);
    } else {
      setError(ERRORS[res.error] ?? "Pairing failed. Try again.");
    }
  };

  return (
    <form onSubmit={submit} style={{
      display: "flex", flexDirection: "column", gap: 16,
      padding: 24, maxWidth: 420, margin: "0 auto",
    }}>
      <h1 style={{ fontSize: 24, margin: 0 }}>Pair with your Boombox</h1>
      <p style={{ color: "var(--ink2)", margin: 0, fontSize: 14 }}>
        Open Settings → Phone remote on the boombox to turn it on and get a PIN.
      </p>

      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={{ fontSize: 13, color: "var(--ink2)" }}>
          Boombox address
        </span>
        <input
          value={host}
          onChange={(e) => setHost(e.target.value)}
          placeholder="boombox.local — or its IP"
          autoCapitalize="off" autoCorrect="off" spellCheck={false}
          style={inputStyle}
        />
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={{ fontSize: 13, color: "var(--ink2)" }}>PIN</span>
        <input
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))}
          inputMode="numeric" placeholder="6 digits"
          style={{ ...inputStyle, letterSpacing: "0.3em" }}
        />
      </label>

      {error && (
        <div role="alert" style={{ color: "#ff7878", fontSize: 14 }}>
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={busy || pin.length !== 6 || host.trim() === ""}
        style={{
          padding: "14px 16px", borderRadius: 12, border: 0,
          background: "var(--accent)", color: "var(--bg)",
          fontSize: 16, fontWeight: 700,
          opacity: busy || pin.length !== 6 || !host.trim() ? 0.5 : 1,
        }}
      >
        {busy ? "Pairing…" : "Pair"}
      </button>
    </form>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "12px 14px", borderRadius: 10,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", fontSize: 18,
};
