import { useRemote } from "../state/store";

const APP_VERSION = "Phase 2B";

/** Compact settings overlay. Shown when the user taps the fixed gear
 *  button. Covers identity (which boombox, which server) and the few
 *  per-user actions that don't fit cleanly on a tab — mic toggle and
 *  the explicit unpair-this-device escape hatch. Dismiss by tapping
 *  outside or the × button. */
export function SettingsSheet(
  { base, onClose, onUnpair }: {
    base: string;
    onClose: () => void;
    onUnpair: () => void;
  },
) {
  const { state, command } = useRemote();
  const micOn = !!state?.mic_on;
  const sleepSec = state?.sleep_timer_s ?? null;
  const sleepLabel = sleepSec == null
    ? "Off — tap to set"
    : `${Math.max(1, Math.round(sleepSec / 60))}m — tap to cycle`;

  const unpair = () => {
    if (!window.confirm(
      "Unpair this device from the boombox? You'll need a fresh PIN to reconnect.",
    )) return;
    onUnpair();
  };

  return (
    <div role="dialog" aria-label="Settings"
         onClick={onClose}
         style={{
           position: "fixed", inset: 0, zIndex: 100,
           background: "rgba(0,0,0,0.55)",
           display: "flex", alignItems: "center", justifyContent: "center",
           padding: 16,
         }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        maxWidth: 380, width: "100%", maxHeight: "80vh", overflowY: "auto",
        background: "var(--panel)", borderRadius: 12,
        border: "1px solid var(--rule)", padding: 16,
      }}>
        <header style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", marginBottom: 14 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Settings</h2>
          <button type="button" onClick={onClose}
                  aria-label="Close"
                  style={{ background: "transparent", border: 0,
                           color: "var(--ink2)", fontSize: 22,
                           cursor: "pointer", lineHeight: 1 }}>×</button>
        </header>

        <Row label="Paired with">
          {state?.boombox?.name ?? "—"}
        </Row>
        <Row label="Server">
          <code style={{ fontFamily: "var(--mono)", fontSize: 12,
                          color: "var(--ink2)" }}>{base}</code>
        </Row>
        <Row label="App build">{APP_VERSION}</Row>

        <div style={{ height: 1, background: "var(--rule)",
                      margin: "16px 0" }} />

        <Row label="Microphone">
          <button type="button"
                  onClick={() => command("mic_karaoke")}
                  aria-pressed={micOn}
                  style={pillBtn(micOn)}>
            {micOn ? "On — tap to mute" : "Off — tap to enable"}
          </button>
        </Row>

        <Row label="Sleep timer">
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end",
                         flexWrap: "wrap" }}>
            <SleepButton
              label={sleepLabel}
              active={sleepSec != null}
              onPress={() => command("sleep_timer")}
            />
            {sleepSec != null && (
              <button type="button"
                      onClick={() => command("sleep_timer_off")}
                      style={pillBtn(false)}>
                Cancel
              </button>
            )}
          </div>
        </Row>

        <div style={{ height: 1, background: "var(--rule)",
                      margin: "16px 0" }} />

        <button type="button" onClick={unpair} style={{
          width: "100%", padding: "12px 14px", borderRadius: 8,
          border: "1px solid var(--accent2)", background: "transparent",
          color: "var(--accent2)", fontSize: 14, cursor: "pointer",
        }}>
          Unpair this device
        </button>
      </div>
    </div>
  );
}

const pillBtn = (active: boolean): React.CSSProperties => ({
  padding: "6px 14px", borderRadius: 999, fontSize: 13,
  border: "1px solid var(--rule)",
  background: active ? "var(--accent)" : "var(--panel)",
  color: active ? "var(--bg)" : "var(--ink)",
  cursor: "pointer",
});

/** Sleep timer button. Backed by the dispatcher's `sleep_timer` action —
 *  short-press cycles 15→30→60→off, long-press cancels. We surface the
 *  cancel via a held-down pointer with a 600 ms timeout. */
function SleepButton(
  { label, active, onPress }: {
    label: string; active: boolean; onPress: () => void;
  },
) {
  return (
    <button type="button"
            onClick={onPress}
            aria-pressed={active}
            style={pillBtn(active)}>
      {label}
    </button>
  );
}

function Row({ label, children }: {
  label: string; children: React.ReactNode;
}) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between",
      alignItems: "center", gap: 12, padding: "6px 0",
    }}>
      <span style={{ color: "var(--ink2)", fontSize: 13,
                      textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {label}
      </span>
      <span style={{ textAlign: "right", minWidth: 0,
                      overflow: "hidden", textOverflow: "ellipsis",
                      whiteSpace: "nowrap" }}>{children}</span>
    </div>
  );
}
