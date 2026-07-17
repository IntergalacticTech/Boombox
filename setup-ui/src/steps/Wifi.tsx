import { useEffect, useState } from "react";
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

  const join = async (net: WifiNetwork) => {
    setJoinError(null);
    setBusy(true);
    try {
      const r = await api.put<WifiJoinResult>("wifi", {
        ssid: net.ssid, psk: net.secured ? psk : "",
      });
      setBusy(false);
      if (!r.ok || !r.connected) {
        setJoinError(r.error ?? "Couldn't join that network.");
        return;
      }
      const info = { ssid: r.ssid ?? net.ssid, ip: r.ip ?? "" };
      setJoined(info);
      update({ wifiConnected: true, wifiSsid: info.ssid, wifiIp: info.ip });
    } catch {
      setBusy(false);
      setJoinError("Couldn't reach the Boombox. Try again.");
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

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
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
                <span aria-hidden style={{ color: "var(--ink2)" }}>
                  {net.secured ? "🔒" : ""}
                </span>
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
                </div>
              )}
            </div>
          );
        })}
      </div>

      {joinError && <ErrorText>{joinError}</ErrorText>}

      <NavRow
        onBack={back}
        secondary={<SecondaryButton onClick={next}>Skip Wi-Fi</SecondaryButton>}
      />
    </StepBody>
  );
}
