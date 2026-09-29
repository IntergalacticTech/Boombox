import { useCallback, useMemo, useState } from "react";
import { loadPairing, clearPairing } from "./lib/pairing";
import type { Pairing } from "./lib/pairing";
import { makeHttpTransport } from "./transport/select";
import { TransportProvider, useRemote } from "./state/store";
import { ApiProvider, makeApi } from "./lib/api";
import { Pairing as PairingScreen } from "./screens/Pairing";
import { AppShell } from "./components/AppShell";
import { SettingsSheet } from "./components/SettingsSheet";
import { InstallBanner } from "./components/InstallBanner";
import { MovedHint } from "./components/MovedHint";

/** Where the API lives. Served by a boombox, the app always talks to its own
 *  origin (same-origin: no CORS, and an IP-vs-.local choice made at pairing
 *  can't strand it); the stored pairing base only matters under `vite dev`. */
export function apiBase(pairing: Pairing, dev: boolean = import.meta.env.DEV): string {
  return dev ? pairing.base : window.location.origin;
}

function NoLongerPaired({ onUnpair }: { onUnpair: () => void }) {
  return (
    <Centered>
      <h2>This phone is no longer paired</h2>
      <p style={{ color: "var(--ink2)" }}>
        It was unpaired from the boombox. Pair again to reconnect.
      </p>
      <button onClick={onUnpair} style={linkBtn}>Pair again</button>
    </Centered>
  );
}

/** Inside the providers: connection status first, then the app shell. */
function Remote({ base, onUnpair }: { base: string; onUnpair: () => void }) {
  const { state, status } = useRemote();
  const [settingsOpen, setSettingsOpen] = useState(false);

  if (status === "disabled") {
    return (
      <Centered>
        <h2>Remote access is off</h2>
        <p style={{ color: "var(--ink2)" }}>
          Turn it on in the boombox's Settings → Phone remote, then this will
          reconnect automatically.
        </p>
      </Centered>
    );
  }
  if (status === "unauthorized") return <NoLongerPaired onUnpair={onUnpair} />;

  const hasState = state !== null;
  if (!hasState && (status === "connecting" || status === "error" ||
                    status === "unavailable")) {
    return (
      <Centered>
        <p style={{ color: "var(--ink2)" }}>
          {status === "connecting" ? "Connecting…"
            : status === "unavailable" ? "Boombox temporarily unavailable…"
            : "Can't reach the boombox."}
        </p>
      </Centered>
    );
  }

  return (
    <>
      {(status === "connecting" || status === "unavailable" ||
        status === "error") && (
        <div role="status" style={{
          position: "fixed", top: 0, left: 0, right: 0, zIndex: 20,
          padding: "6px 12px", textAlign: "center", fontSize: 12,
          background: "var(--panel)", color: "var(--ink2)",
          borderBottom: "1px solid var(--rule)",
        }}>
          {status === "connecting" ? "Reconnecting…"
            : status === "unavailable" ? "Boombox restarting — will reconnect"
            : "Connection lost — retrying"}
        </div>
      )}
      <InstallBanner />
      <AppShell onOpenSettings={() => setSettingsOpen(true)} />
      {settingsOpen && (
        <SettingsSheet base={base}
                       onClose={() => setSettingsOpen(false)}
                       onUnpair={() => { setSettingsOpen(false); onUnpair(); }} />
      )}
    </>
  );
}

function Main() {
  const [pairing, setPairing] = useState<Pairing | null>(() => loadPairing());
  // Any API call answering 401 = this device was unpaired on the boombox.
  const [revoked, setRevoked] = useState(false);
  const unpair = useCallback(() => {
    clearPairing();
    setRevoked(false);
    setPairing(null);
  }, []);
  const base = pairing ? apiBase(pairing) : "";
  const api = useMemo(
    () => (pairing ? makeApi(base, pairing.token, () => setRevoked(true)) : null),
    [base, pairing]);
  const transport = useMemo(
    () => (pairing ? makeHttpTransport(base, pairing.token) : null), [base, pairing]);

  if (!pairing || !api || !transport) {
    return <PairingScreen onPaired={(p) => { setRevoked(false); setPairing(p); }} />;
  }
  if (revoked) return <NoLongerPaired onUnpair={unpair} />;

  // `key` forces a fresh TransportProvider when the pairing changes.
  return (
    <ApiProvider api={api}>
      <TransportProvider key={pairing.token} transport={transport}>
        <Remote base={base} onUnpair={unpair} />
      </TransportProvider>
    </ApiProvider>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      minHeight: "100%", display: "grid", placeItems: "center",
      padding: 24, textAlign: "center",
    }}>
      <div style={{ maxWidth: 420 }}>{children}</div>
    </div>
  );
}

const linkBtn: React.CSSProperties = {
  marginTop: 12, padding: "10px 18px", borderRadius: 10,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", fontSize: 15, cursor: "pointer",
};

export default function App() {
  return (
    <>
      <MovedHint />
      <Main />
    </>
  );
}
