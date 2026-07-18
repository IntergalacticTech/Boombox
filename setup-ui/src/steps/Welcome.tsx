import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import type { WizardCtx } from "../App";
import type { SessionResult } from "../lib/types";
import { PrimaryButton, StepBody } from "../components/ui";

/** Step 1 — greet and, on the kiosk, offer a QR to finish from a phone. */
export function Welcome({ ctx }: { ctx: WizardCtx }) {
  const { api, status, next } = ctx;
  const [handoff, setHandoff] = useState<SessionResult | null>(null);

  useEffect(() => {
    // Only the kiosk may mint a session for the phone handoff; from a phone
    // POST session 403s, so we simply skip it.
    if (!api.isKiosk) return;
    let alive = true;
    api.post<SessionResult>("session")
      .then((r) => { if (alive) setHandoff(r); })
      .catch(() => { /* handoff is optional — kiosk setup works without it */ });
    return () => { alive = false; };
  }, [api]);

  return (
    <StepBody
      title="Welcome to your Boombox"
      subtitle="Let's get it set up. This takes a couple of minutes."
    >
      <div style={{
        padding: "10px 14px", borderRadius: 12, background: "var(--panel)",
        border: "1px solid var(--rule)", display: "flex",
        alignItems: "baseline", gap: 10,
      }}>
        <span style={{ fontSize: 13, color: "var(--ink2)" }}>This device</span>
        <span style={{ fontSize: 17, fontWeight: 700 }}>
          {status.identity.name}
        </span>
        <span style={{ fontSize: 13, color: "var(--ink2)" }}>
          {status.identity.hostname}
        </span>
      </div>

      {handoff && (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "center",
          gap: 18,
        }}>
          <div style={{
            background: "#fff", padding: 8, borderRadius: 8, flex: "none",
          }}>
            <QRCodeSVG value={handoff.url} size={116} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
            <div style={{ fontSize: 13, color: "var(--ink2)" }}>
              Scan to set up from your phone — or visit
            </div>
            <div style={{
              fontFamily: "var(--mono)", fontSize: 15,
              color: "var(--accent2)", overflowWrap: "anywhere",
            }}>
              {handoff.base_url}
            </div>
            <div style={{ fontSize: 13, color: "var(--ink2)" }}>
              and enter code{" "}
              <span style={{
                fontFamily: "var(--mono)", fontSize: 16, fontWeight: 700,
                color: "var(--ink)", letterSpacing: "0.18em",
              }}>
                {handoff.code}
              </span>
            </div>
          </div>
        </div>
      )}

      <PrimaryButton onClick={next}>Get started</PrimaryButton>
    </StepBody>
  );
}
