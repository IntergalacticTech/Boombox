// ui/src/lib/UpdatesPanel.tsx — Updates section for SettingsDrawer.
// Quiet UI: no badge, no overlay. Status is only visible when the user
// opens Settings. Auto-update on by default; user can flip channel,
// window, and trigger a manual install / rollback.

import { useEffect, useState } from "react";
import {
  Channel,
  UpdaterStatus,
  check,
  fetchLog,
  getStatus,
  installNow,
  rollback,
  saveConfig,
} from "./updaterApi";

function fmtAgo(ts: number): string {
  if (!ts) return "never";
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  return `${Math.floor(sec / 86400)} d ago`;
}

export function UpdatesPanel() {
  const [status, setStatus] = useState<UpdaterStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [logText, setLogText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = async () => {
    try { setStatus(await getStatus()); }
    catch (e) { setErr(String(e)); }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, []);

  if (!status) {
    return (
      <div className="settings-section">
        <h3>Updates</h3>
        <div>Loading… {err && <span style={{ color: "tomato" }}>{err}</span>}</div>
      </div>
    );
  }

  const upToDate = !status.available_version
    || status.installed_version === status.available_version;
  const installing = status.state_machine !== "idle";

  const update = async (patch: Partial<typeof status>) => {
    const next = { ...status, ...patch };
    try {
      await saveConfig({
        auto: next.auto, channel: next.channel,
        window_start: next.window_start,
        window_duration_min: next.window_duration_min,
      });
      setStatus(next);
    } catch (e) { setErr(String(e)); }
  };

  const wrap = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setErr(null);
    try { await fn(); await refresh(); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(null); }
  };

  return (
    <div className="settings-section">
      <h3>Updates</h3>

      <div>
        {upToDate
          ? <>Up to date — <strong>{status.installed_version}</strong> ({status.channel})</>
          : <>Update available: <strong>{status.available_version}</strong> (installed: {status.installed_version})</>
        }
        <div style={{ opacity: 0.7, fontSize: "0.85em" }}>
          Last checked: {fmtAgo(status.last_check_ts)}
        </div>
        {installing && (
          <div style={{ opacity: 0.7, fontSize: "0.85em" }}>
            Installing… ({status.state_machine})
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }}>
        <span>Auto-update</span>
        <button disabled={busy !== null} onClick={() => update({ auto: !status.auto })}>
          {status.auto ? "On" : "Off"}
        </button>
        <span style={{ marginLeft: 12 }}>Channel</span>
        <select
          value={status.channel}
          disabled={busy !== null}
          onChange={(e) => update({ channel: e.target.value as Channel })}
        >
          <option value="stable">stable</option>
          <option value="edge">edge</option>
        </select>
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }}>
        <span>Window</span>
        <input
          type="time"
          value={status.window_start}
          disabled={busy !== null}
          onChange={(e) => update({ window_start: e.target.value })}
          style={{ width: 90 }}
        />
        <span>for</span>
        <input
          type="number"
          min={1} max={1440}
          value={status.window_duration_min}
          disabled={busy !== null}
          onChange={(e) => update({ window_duration_min: Number(e.target.value) })}
          style={{ width: 70 }}
        />
        <span>min</span>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <button disabled={busy !== null}
                onClick={() => wrap("check", check)}>
          {busy === "check" ? "Checking…" : "Check now"}
        </button>
        <button disabled={busy !== null || upToDate}
                onClick={() => wrap("install", () => installNow({ force: true }))}>
          {busy === "install" ? "Installing…" : "Install now"}
        </button>
        <button disabled={busy !== null}
                onClick={() => wrap("rollback", rollback)}>
          {busy === "rollback" ? "Rolling back…" : "Rollback"}
        </button>
      </div>

      {status.last_attempt && (
        <div style={{ marginTop: 8, fontSize: "0.9em" }}>
          Last attempt: {new Date(status.last_attempt.ts * 1000).toLocaleString()} —
          <strong> {status.last_attempt.result}</strong>
          {status.last_attempt.error && (
            <div style={{ color: "tomato" }}>{status.last_attempt.error}</div>
          )}
          <button style={{ marginTop: 4 }}
                  onClick={async () => setLogText(await fetchLog(500))}>
            View log
          </button>
        </div>
      )}

      {logText !== null && (
        <pre style={{
          marginTop: 8, maxHeight: 200, overflow: "auto",
          background: "#111", color: "#ddd", padding: 8, fontSize: "0.8em",
        }}>
          {logText}
        </pre>
      )}

      {err && <div style={{ color: "tomato", marginTop: 6 }}>{err}</div>}
    </div>
  );
}
