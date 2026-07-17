import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import type { WizardCtx } from "../App";
import type { SessionResult } from "../lib/types";
import { PrimaryButton, StepBody } from "../components/ui";

/** Step 1 — greet and, on the kiosk, offer a QR to finish from a phone. */
export function Welcome({ ctx }: { ctx: WizardCtx }) {
  const { api, status, next } = ctx;
  const [handoffUrl, setHandoffUrl] = useState<string | null>(null);

  useEffect(() => {
    // Only the kiosk (no hash token) may mint a session for the handoff QR;
    // from a phone POST session 403s, so we simply skip it.
    if (!api.isKiosk) return;
    let alive = true;
    api.post<SessionResult>("session")
      .then((r) => { if (alive) setHandoffUrl(r.url); })
      .catch(() => { /* QR is optional — kiosk setup works without it */ });
    return () => { alive = false; };
  }, [api]);

  return (
    <StepBody
      title="Welcome to your Boombox"
      subtitle="Let's get it set up. This takes a couple of minutes."
    >
      <div style={{
        padding: 16, borderRadius: 12, background: "var(--panel)",
        border: "1px solid var(--rule)",
      }}>
        <div style={{ fontSize: 13, color: "var(--ink2)" }}>This device</div>
        <div style={{ fontSize: 20, fontWeight: 700, marginTop: 2 }}>
          {status.identity.name}
        </div>
        <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 2 }}>
          {status.identity.hostname}
        </div>
      </div>

      {handoffUrl && (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          gap: 10, paddingTop: 4,
        }}>
          <div style={{ background: "#fff", padding: 12, borderRadius: 8 }}>
            <QRCodeSVG value={handoffUrl} size={168} />
          </div>
          <div style={{ fontSize: 13, color: "var(--ink2)", textAlign: "center" }}>
            Or scan to finish setup from your phone.
          </div>
        </div>
      )}

      <PrimaryButton onClick={next}>Get started</PrimaryButton>
    </StepBody>
  );
}
