import { useState } from "react";
import { loadPairing, clearPairing } from "./lib/pairing";
import type { Pairing } from "./lib/pairing";
import { makeHttpTransport } from "./transport/select";
import { TransportProvider, useRemote } from "./state/store";
import { ApiProvider, makeApi } from "./lib/api";
import { Pairing as PairingScreen } from "./screens/Pairing";
import { NowPlaying } from "./screens/NowPlaying";
import { Files } from "./screens/Files";
import { Library } from "./screens/Library";
import { Playlists } from "./screens/Playlists";
import { Search } from "./screens/Search";
import { TabBar, type Tab } from "./components/TabBar";
import { SettingsSheet } from "./components/SettingsSheet";
import { MiniPlayer } from "./components/MiniPlayer";

/** Inside the provider: routes on connection status, then on selected tab. */
function Remote(
  { base, onUnpair }: { base: string; onUnpair: () => void },
) {
  const { state, status } = useRemote();
  const [tab, setTab] = useState<Tab>("now");
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Terminal states always take over — the user has to act before the app
  // is usable again.
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

  // Transient states: if we already have rendered state, keep showing it
  // and overlay a thin banner instead of full-screen replacing the UI.
  // The initial-load case (no state yet) still gets the centered message.
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
      <button type="button" aria-label="Settings"
              onClick={() => setSettingsOpen(true)}
              style={{
                position: "fixed", top: 12, right: 12, zIndex: 15,
                width: 36, height: 36, borderRadius: 18,
                border: "1px solid var(--rule)", background: "var(--panel)",
                color: "var(--ink2)", fontSize: 18, cursor: "pointer",
                lineHeight: 1,
              }}>⚙</button>
      {tab === "now" && <NowPlaying />}
      {tab === "library" && <Library />}
      {tab === "playlists" && <Playlists />}
      {tab === "search" && <Search />}
      {tab === "files" && <Files />}
      {tab !== "now" && <MiniPlayer onOpenNow={() => setTab("now")} />}
      <TabBar active={tab} onChange={setTab} />
      {settingsOpen && (
        <SettingsSheet base={base}
                       onClose={() => setSettingsOpen(false)}
                       onUnpair={() => { setSettingsOpen(false); onUnpair(); }} />
      )}
    </>
  );
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
    <ApiProvider api={makeApi(pairing.base, pairing.token)}>
      <TransportProvider
        key={pairing.token}
        transport={makeHttpTransport(pairing.base, pairing.token)}
      >
        <Remote base={pairing.base} onUnpair={unpair} />
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
