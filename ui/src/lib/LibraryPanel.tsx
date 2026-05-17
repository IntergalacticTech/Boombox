// LibraryPanel — SettingsDrawer section for Home Library source config.
// Mirrors UpdatesPanel.tsx in layout: 5 s health poll (via homeLibrary),
// inline errors, touch-friendly Test/Save/Sync buttons.

import { useEffect, useState } from "react";
import {
  getSource, putSource, testSource, runSync,
  type SourceConfig,
} from "./libraryApi";
import { useSyncStatus, refreshNow } from "./homeLibrary";

function fmtAgo(ts: number): string {
  if (!ts) return "never";
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  return `${Math.floor(sec / 86400)} d ago`;
}

export function LibraryPanel() {
  const status = useSyncStatus();
  const [form, setForm] = useState<SourceConfig & { password: string }>(
    { url: "", username: "", password: "" }
  );
  const [busy, setBusy] = useState<"" | "test" | "save" | "sync">("");
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    getSource().then(s => setForm(f => ({ ...f, url: s.url, username: s.username })))
               .catch(() => { /* surface via status */ });
  }, []);

  const update = (patch: Partial<typeof form>) => setForm(f => ({ ...f, ...patch }));

  const doTest = async () => {
    setBusy("test"); setMsg(null);
    try {
      const r = await testSource(form);
      setMsg(r.ok ? { kind: "ok", text: "Connected" }
                  : { kind: "err", text: r.error || "Failed" });
    } finally { setBusy(""); }
  };
  const doSave = async () => {
    setBusy("save"); setMsg(null);
    try {
      await putSource(form);
      setMsg({ kind: "ok", text: "Saved · syncing…" });
      await refreshNow();
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : String(e) });
    } finally { setBusy(""); }
  };
  const doSync = async () => {
    setBusy("sync"); setMsg(null);
    try { await runSync(); await refreshNow(); }
    catch (e) { setMsg({ kind: "err", text: String(e) }); }
    finally { setBusy(""); }
  };

  const dotColor =
    status.syncing ? "#ffb84d" :
    status.reachable ? "#9bf2c0" :
    "rgba(255,255,255,0.35)";

  return (
    <div style={{ padding: "14px 16px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 10 }}>Home Library</div>

      <div style={{ display: "grid", gap: 8, marginBottom: 10 }}>
        <label style={labelStyle}>
          <span>Source URL</span>
          <input
            type="url"
            value={form.url}
            placeholder="http://192.168.1.223:4533"
            onChange={(e) => update({ url: e.target.value })}
            style={inputStyle}
          />
        </label>
        <label style={labelStyle}>
          <span>Username</span>
          <input
            name="username"
            value={form.username}
            onChange={(e) => update({ username: e.target.value })}
            style={inputStyle}
          />
        </label>
        <label style={labelStyle}>
          <span>Password</span>
          <input
            type="password"
            value={form.password}
            onChange={(e) => update({ password: e.target.value })}
            placeholder="••••••••"
            style={inputStyle}
          />
        </label>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{
          width: 10, height: 10, borderRadius: 999, background: dotColor,
        }}/>
        <span style={{ fontSize: 13, color: "rgba(255,255,255,0.78)" }}>
          {status.syncing
            ? "Syncing…"
            : status.reachable
              ? `Connected · last sync ${fmtAgo(status.lastSyncTs)}`
              : "Library unreachable"}
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button disabled={!!busy} onClick={doTest} style={btn("rgba(255,255,255,0.10)")}>
          {busy === "test" ? "Testing…" : "Test"}
        </button>
        <button disabled={!!busy} onClick={doSave} style={btn("#5be7ff")}>
          {busy === "save" ? "Saving…" : "Save"}
        </button>
        <button disabled={!!busy} onClick={doSync} style={btn("rgba(255,255,255,0.10)")}>
          {busy === "sync" ? "Syncing…" : "Sync now"}
        </button>
      </div>

      {msg && (
        <div style={{
          marginTop: 8, fontSize: 13,
          color: msg.kind === "ok" ? "#9bf2c0" : "#ff7a35",
        }}>{msg.kind === "ok" ? "✓ " : "✗ "}{msg.text}</div>
      )}
    </div>
  );
}

const labelStyle = {
  display: "grid", gridTemplateColumns: "110px 1fr", alignItems: "center", gap: 10,
  fontSize: 13, color: "rgba(255,255,255,0.78)",
} as const;
const inputStyle = {
  padding: "10px 12px", minHeight: 44,
  background: "rgba(255,255,255,0.06)",
  color: "#fff",
  border: "1px solid rgba(255,255,255,0.14)",
  borderRadius: 8,
  fontSize: 14,
  fontFamily: "Inter, system-ui, sans-serif",
  outline: "none",
} as const;
function btn(bg: string) {
  return {
    padding: "10px 14px", minHeight: 44,
    background: bg, color: bg === "rgba(255,255,255,0.10)" ? "#fff" : "#000",
    border: "none", borderRadius: 999,
    fontWeight: 700, fontSize: 13, letterSpacing: "0.06em",
    cursor: "pointer",
  } as const;
}
