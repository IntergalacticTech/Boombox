import { useEffect, useRef, useState } from "react";
import type { WizardCtx } from "../App";
import type { WifiNetwork, WifiScanResult, WifiJoinResult } from "../lib/types";
import {
  PrimaryButton, SecondaryButton, Field, ErrorText, StepBody, NavRow,
  inputStyle,
} from "../components/ui";

/** Step 3 — join Wi-Fi. Skipped automatically on Ethernet-only devices. */
export function Wifi({ ctx }: { ctx: WizardCtx }) {
  const { api, status, update, next, back } = ctx;
  const hasWifi = status.wifi.present;

  const [scanning, setScanning] = useState(hasWifi);
  const [networks, setNetworks] = useState<WifiNetwork[]>([]);
  const [noWifi, setNoWifi] = useState(!hasWifi);
  const [scanError, setScanError] = useState<string | null>(null);

  const [selected, setSelected] = useState<WifiNetwork | null>(null);
  const [psk, setPsk] = useState("");
  const [busy, setBusy] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [joined, setJoined] = useState<{ ssid: string; ip: string } | null>(null);

  useEffect(() => {
    if (!hasWifi) return;
    let alive = true;
    setScanning(true);
    // The scan may take ~30s while the adapter surveys the band.
    api.get<WifiScanResult>("wifi/scan")
      .then((r) => {
        if (!alive) return;
        if (r.no_wifi) { setNoWifi(true); return; }
        if (!r.ok) { setScanError(r.error ?? "Wi-Fi scan failed."); return; }
        setNetworks(r.networks ?? []);
      })
      .catch(() => { if (alive) setScanError("Wi-Fi scan failed."); })
      .finally(() => { if (alive) setScanning(false); });
    return () => { alive = false; };
  }, [api, hasWifi]);

  const [phase, setPhase] = useState<string | null>(null);
  const settledRef = useRef(false);

  const join = async (net: WifiNetwork) => {
    setJoinError(null);
    setBusy(true);
    settledRef.current = false;
    setPhase(`Connecting to ${net.ssid}…`);
    // Progress narration while the device associates + DHCPs (the backend
    // answers a wrong passphrase in ~20s; success typically 5–15s).
    const phases = window.setTimeout(
      () => setPhase("Checking the passphrase…"), 6000);
    const phases2 = window.setTimeout(
      () => setPhase("Still working — getting an address…"), 22000);
    // Hard cap: never leave the user staring at a spinner. The backend
    // bounds itself well under this; tripping it means something is stuck.
    const timer = window.setTimeout(() => {
      if (settledRef.current) return;
      settledRef.current = true;
      setBusy(false);
      setJoinError("This is taking too long — the Boombox may still be "
        + "trying. Give it a moment, then rescan or skip Wi-Fi.");
    }, 60000);
    try {
      const r = await api.put<WifiJoinResult>("wifi", {
        ssid: net.ssid, psk: net.secured ? psk : "",
      });
      if (settledRef.current) return;   // the hard cap already spoke
      settledRef.current = true;
      setBusy(false);
      if (!r.ok || !r.connected) {
        setJoinError(r.error
          ?? `Couldn't join ${net.ssid} — check the passphrase and try again.`);
        return;
      }
      const info = { ssid: r.ssid ?? net.ssid, ip: r.ip ?? "" };
      setJoined(info);
      update({ wifiConnected: true, wifiSsid: info.ssid, wifiIp: info.ip });
    } catch {
      if (settledRef.current) return;
      settledRef.current = true;
      setBusy(false);
      setJoinError("Couldn't reach the Boombox. Try again.");
    } finally {
      window.clearTimeout(phases);
      window.clearTimeout(phases2);
      window.clearTimeout(timer);
      setPhase(null);
    }
  };

  const onSelect = (net: WifiNetwork) => {
    setJoinError(null);
    if (!net.secured) { setSelected(net); void join(net); return; }
    setSelected(net);
    setPsk("");
  };

  // Ethernet / no Wi-Fi hardware — nothing to do here.
  if (noWifi) {
    return (
      <StepBody
        title="Wi-Fi"
        subtitle="This device is on Ethernet — Wi-Fi isn't required."
      >
        <NavRow
          onBack={back}
          primary={<PrimaryButton onClick={next}>Next</PrimaryButton>}
        />
      </StepBody>
    );
  }

  if (joined) {
    return (
      <StepBody title="Wi-Fi connected">
        <div style={{
          padding: 16, borderRadius: 12, background: "var(--panel)",
          border: "1px solid var(--rule)",
        }}>
          <div style={{ fontSize: 16, fontWeight: 700 }}>✓ {joined.ssid}</div>
          {joined.ip && (
            <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 4 }}>
              IP address {joined.ip}
            </div>
          )}
        </div>
        <NavRow
          onBack={back}
          primary={<PrimaryButton onClick={next}>Next</PrimaryButton>}
        />
      </StepBody>
    );
  }

  return (
    <StepBody
      title="Join Wi-Fi"
      subtitle="Pick your network so the Boombox can reach the internet."
    >
      {scanning && (
        <div style={{ color: "var(--ink2)", fontSize: 14 }}>
          Scanning for networks… this can take up to 30 seconds.
        </div>
      )}

      {scanError && <ErrorText>{scanError}</ErrorText>}

      {!scanning && networks.length === 0 && !scanError && (
        <div style={{ color: "var(--ink2)", fontSize: 14 }}>
          No networks found.
        </div>
      )}

      <div style={{
        display: "flex", flexDirection: "column", gap: 8,
        // Lock the list while a join is in flight so taps elsewhere can't
        // stack a second attempt on top of the first.
        pointerEvents: busy ? "none" : "auto",
        opacity: busy ? 0.55 : 1,
      }}>
        {networks.map((net) => {
          const isSel = selected?.ssid === net.ssid;
          return (
            <div key={net.ssid}>
              <button
                type="button"
                onClick={() => onSelect(net)}
                style={{
                  display: "flex", justifyContent: "space-between",
                  alignItems: "center", width: "100%", minHeight: 48,
                  padding: "12px 14px", borderRadius: 10, cursor: "pointer",
                  border: `1px solid ${isSel ? "var(--accent)" : "var(--rule)"}`,
                  background: "var(--panel)", color: "var(--ink)", fontSize: 16,
                }}
              >
                <span>{net.ssid}</span>
                {/* Inline SVG padlock — the kiosk font has no emoji glyphs. */}
                {net.secured && (
                  <svg aria-hidden width="14" height="16" viewBox="0 0 14 16"
                       style={{ flex: "none" }}>
                    <rect x="1" y="7" width="12" height="8" rx="2"
                          fill="var(--ink2)" />
                    <path d="M4 7V5a3 3 0 0 1 6 0v2" fill="none"
                          stroke="var(--ink2)" strokeWidth="2" />
                  </svg>
                )}
              </button>
              {isSel && net.secured && (
                <div style={{
                  display: "flex", flexDirection: "column", gap: 10,
                  padding: "12px 4px 4px",
                }}>
                  <Field label="Passphrase">
                    <input
                      type="password"
                      value={psk}
                      onChange={(e) => setPsk(e.target.value)}
                      placeholder="8–63 characters"
                      autoCapitalize="off" autoCorrect="off" spellCheck={false}
                      aria-label="Passphrase"
                      style={inputStyle}
                    />
                  </Field>
                  <PrimaryButton
                    onClick={() => join(net)}
                    disabled={busy || psk.length < 8 || psk.length > 63}
                  >
                    {busy ? "Joining…" : "Join"}
                  </PrimaryButton>
                  {isSel && phase && (
                    <div style={{ color: "var(--ink2)", fontSize: 13 }}>
                      {phase}
                    </div>
                  )}
                  {isSel && joinError && <ErrorText>{joinError}</ErrorText>}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Errors for open networks (no inline panel to anchor to). */}
      {joinError && !selected?.secured && <ErrorText>{joinError}</ErrorText>}
      {phase && !selected?.secured && (
        <div style={{ color: "var(--ink2)", fontSize: 13 }}>{phase}</div>
      )}

      <NavRow
        onBack={back}
        secondary={<SecondaryButton onClick={next}>Skip Wi-Fi</SecondaryButton>}
      />
    </StepBody>
  );
}
