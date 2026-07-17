import { useState } from "react";
import type { WizardCtx } from "../App";
import type { OkResult } from "../lib/types";
import {
  PrimaryButton, ErrorText, StepBody, NavRow,
} from "../components/ui";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", gap: 12,
      padding: "10px 0", borderBottom: "1px solid var(--rule)",
    }}>
      <span style={{ color: "var(--ink2)", fontSize: 14 }}>{label}</span>
      <span style={{ fontSize: 14, textAlign: "right" }}>{value}</span>
    </div>
  );
}

/** Step 7 — review and finish. */
export function Done({ ctx }: { ctx: WizardCtx }) {
  const { api, summary, back } = ctx;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState(false);

  const finish = async () => {
    setError(null);
    setBusy(true);
    try {
      await api.post<OkResult>("complete");
      setBusy(false);
      // On the kiosk, return to the player. On a phone, show a confirmation —
      // the kiosk itself will move on.
      if (api.isKiosk) {
        window.location.href = "/";
        return;
      }
      setFinished(true);
    } catch {
      setBusy(false);
      setError("Couldn't finish setup. Try again.");
    }
  };

  if (finished) {
    return (
      <StepBody
        title="You're all set"
        subtitle="The Boombox is ready. You can put your phone down."
      >
        {summary.rebootRequired && (
          <div style={{ color: "var(--ink2)", fontSize: 14 }}>
            Reboot the Boombox when convenient to finish applying the new
            network name.
          </div>
        )}
      </StepBody>
    );
  }

  return (
    <StepBody
      title="Review & finish"
      subtitle="Here's how your Boombox is set up."
    >
      <div>
        <Row label="Name" value={summary.name} />
        <Row label="Wi-Fi"
             value={summary.wifiConnected
               ? (summary.wifiSsid || "Connected")
               : "Not configured"} />
        <Row label="Music"
             value={summary.musicConfigured ? "Connected" : "Not configured"} />
        <Row label="Video"
             value={summary.videoMode === "remote" ? "Own server" : "Built-in Jellyfin"} />
        <Row label="Phone remote"
             value={summary.remoteEnabled ? "Enabled" : "Off"} />
      </div>

      {summary.rebootRequired && (
        <div style={{ color: "var(--ink2)", fontSize: 14 }}>
          Reboot the Boombox when convenient to finish applying the new network
          name.
        </div>
      )}

      {error && <ErrorText>{error}</ErrorText>}

      <NavRow
        onBack={back}
        primary={
          <PrimaryButton onClick={finish} disabled={busy}>
            {busy ? "Finishing…" : "Finish setup"}
          </PrimaryButton>
        }
      />
    </StepBody>
  );
}
