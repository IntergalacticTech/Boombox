import { useState } from "react";
import { loadPairing, clearPairing } from "./lib/pairing";
import type { Pairing } from "./lib/pairing";
import { makeHttpTransport } from "./transport/select";
import { TransportProvider, useRemote } from "./state/store";
import { Pairing as PairingScreen } from "./screens/Pairing";
import { NowPlaying } from "./screens/NowPlaying";

/** Inside the provider: routes on connection status. */
function Remote({ onUnpair }: { onUnpair: () => void }) {
  const { status } = useRemote();

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
  if (status === "unauthorized") {
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
  if (status === "unavailable") {
    return (
      <Centered>
        <h2>Boombox temporarily unavailable</h2>
        <p style={{ color: "var(--ink2)" }}>
          The boombox is reachable but its state service is restarting. This
          will reconnect automatically.
        </p>
      </Centered>
    );
  }
  if (status === "error" || status === "connecting") {
    return (
      <Centered>
        <p style={{ color: "var(--ink2)" }}>
          {status === "connecting" ? "Connecting…" : "Can't reach the boombox."}
        </p>
      </Centered>
    );
  }
  return <NowPlaying />;
}

export default function App() {
  const [pairing, setPairing] = useState<Pairing | null>(() => loadPairing());

  if (!pairing) {
    return <PairingScreen onPaired={setPairing} />;
  }

  const unpair = () => {
    clearPairing();
    setPairing(null);
  };

  // `key` forces a fresh TransportProvider (new transport) when the pairing
  // changes — e.g. after re-pairing.
  return (
    <TransportProvider
      key={pairing.token}
      transport={makeHttpTransport(pairing.base, pairing.token)}
    >
      <Remote onUnpair={unpair} />
    </TransportProvider>
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
