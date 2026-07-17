import { useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import type { WizardCtx } from "../App";
import type { RemoteEnableResult, RemotePairResult } from "../lib/types";
import {
  PrimaryButton, SecondaryButton, ErrorText, StepBody, NavRow,
} from "../components/ui";

/** Step 6 — enable and pair the phone remote (off by default). */
export function Remotes({ ctx }: { ctx: WizardCtx }) {
  const { api, status, summary, update, next, back } = ctx;
  const [enabled, setEnabled] = useState(summary.remoteEnabled);
  const [pin, setPin] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The phone remote PWA lives at /remote/ on port 8090 — derive it from the
  // current host so the QR points at this device.
  const remoteUrl = `http://${location.hostname}:8090/remote/`;

  const enable = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await api.post<RemoteEnableResult>("remote/enable");
      setBusy(false);
      if (!r.ok) { setError("Couldn't enable the phone remote."); return; }
      setEnabled(r.enabled);
      update({ remoteEnabled: r.enabled });
    } catch {
      setBusy(false);
      setError("Couldn't reach the Boombox. Try again.");
    }
  };

  const pair = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await api.post<RemotePairResult>("remote/pair");
      setBusy(false);
      if (!r.ok) { setError("Couldn't start pairing."); return; }
      setPin(r.pin);
    } catch {
      setBusy(false);
      setError("Couldn't reach the Boombox. Try again.");
    }
  };

  return (
    <StepBody
      title="Phone remote"
      subtitle="Control the Boombox from your phone. It's off until you turn it on."
    >
      {!enabled && (
        <PrimaryButton onClick={enable} disabled={busy}>
          {busy ? "Enabling…" : "Enable phone remote"}
        </PrimaryButton>
      )}

      {enabled && !pin && (
        <>
          <div style={{ color: "var(--ink2)", fontSize: 14 }}>
            Phone remote is on.
          </div>
          <PrimaryButton onClick={pair} disabled={busy}>
            {busy ? "Preparing…" : "Pair a phone"}
          </PrimaryButton>
        </>
      )}

      {enabled && pin && (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          gap: 12,
        }}>
          <div style={{
            fontSize: 44, fontWeight: 800, letterSpacing: "0.15em",
            fontFamily: "var(--mono)",
          }}>
            {pin}
          </div>
          <div style={{ background: "#fff", padding: 12, borderRadius: 8 }}>
            <QRCodeSVG value={remoteUrl} size={168} />
          </div>
          <div style={{ fontSize: 14, color: "var(--ink2)", textAlign: "center" }}>
            Open the Boombox remote on your phone and enter this PIN.
          </div>
          <button type="button" onClick={pair} style={{
            background: "none", border: 0, color: "var(--ink2)",
            fontSize: 13, cursor: "pointer",
          }}>Generate a new PIN</button>
        </div>
      )}

      {status.remote.peers.length > 0 && (
        <div style={{
          padding: 14, borderRadius: 12, background: "var(--panel)",
          border: "1px solid var(--rule)",
        }}>
          <div style={{ fontSize: 13, color: "var(--ink2)", marginBottom: 6 }}>
            Paired phones
          </div>
          {status.remote.peers.map((p, i) => (
            <div key={i} style={{ fontSize: 15 }}>{p.label}</div>
          ))}
        </div>
      )}

      {error && <ErrorText>{error}</ErrorText>}

      <NavRow
        onBack={back}
        primary={<PrimaryButton onClick={next}>Next</PrimaryButton>}
        secondary={<SecondaryButton onClick={next}>Skip</SecondaryButton>}
      />
    </StepBody>
  );
}
