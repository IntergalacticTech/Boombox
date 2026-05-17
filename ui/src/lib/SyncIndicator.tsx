// SyncIndicator — 16 px dot in the chrome that reflects Home Library sync state.
//
//   green   = reachable AND fresh sync (online_idle)
//   amber   = syncing (pulse)
//   blue    = reachable + cache present but no successful sync yet (online_due)
//   grey    = unreachable OR no source configured (offline)
//
// Tap → dispatches boombox:open-settings-library which the SettingsDrawer
// listens for to auto-open scrolled to the Library panel.

import { useSyncStatus } from "./homeLibrary";

const STATE_COLOR: Record<string, string> = {
  online_idle: "#9bf2c0",
  syncing:     "#ffb84d",
  online_due:  "#5be7ff",
  offline:     "rgba(255,255,255,0.35)",
};

function computeState(s: ReturnType<typeof useSyncStatus>): keyof typeof STATE_COLOR {
  if (s.syncing) return "syncing";
  if (!s.reachable) return "offline";
  if (s.lastSyncTs > 0) return "online_idle";
  return "online_due";
}

export function SyncIndicator() {
  const status = useSyncStatus();
  const state = computeState(status);

  const open = () => {
    window.dispatchEvent(new CustomEvent("boombox:open-settings-library"));
  };

  return (
    <button
      onClick={open}
      aria-label={`Sync · ${state.replace("_", " ")}`}
      data-state={state}
      style={{
        width: 44, height: 44, minWidth: 44, minHeight: 44,
        border: "1.5px solid rgba(255,255,255,0.20)",
        borderRadius: 999,
        background: "rgba(255,255,255,0.06)",
        display: "grid", placeItems: "center",
        cursor: "pointer",
        flexShrink: 0,
      }}
    >
      <span style={{
        width: 12, height: 12, borderRadius: 999,
        background: STATE_COLOR[state],
        boxShadow: state === "syncing" ? "0 0 8px currentColor" : "none",
        color: STATE_COLOR[state],
        animation: state === "syncing" ? "boombox-sync-pulse 1.4s ease-in-out infinite" : "none",
      }}/>
    </button>
  );
}
