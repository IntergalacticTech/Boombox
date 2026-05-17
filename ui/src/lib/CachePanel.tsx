// CachePanel — SettingsDrawer section for the USB cache drive.
// Stacked bar (reserved | pinned | streamed | free), drive label,
// Clear-streamed button. Updates from the homeLibrary poll.

import { useState } from "react";
import { clearStreamedCache } from "./libraryApi";
import { refreshNow, useCacheStats, useSyncStatus } from "./homeLibrary";

function fmtGB(bytes: number): string {
  if (!bytes) return "0 GB";
  const gb = bytes / 1024 / 1024 / 1024;
  return gb >= 10 ? `${gb.toFixed(0)} GB` : `${gb.toFixed(1)} GB`;
}

export function CachePanel() {
  const stats = useCacheStats();
  const sync = useSyncStatus();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const onClear = async () => {
    if (!window.confirm("Clear all streamed (non-pinned) cache?")) return;
    setBusy(true); setMsg(null);
    try {
      const r = await clearStreamedCache();
      setMsg(`Cleared ${r.cleared} entries`);
      await refreshNow();
    } catch (e) {
      setMsg(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(false); }
  };

  const present = stats?.present ?? sync.cachePresent;

  return (
    <div style={{ padding: "14px 16px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 10 }}>Offline Cache</div>

      {!present || !stats ? (
        <div style={{ fontSize: 13, color: "rgba(255,255,255,0.55)", padding: "8px 0" }}>
          ● Cache drive offline — plug in a USB drive to enable downloads
        </div>
      ) : (
        <>
          <div style={{ fontSize: 12, color: "rgba(255,255,255,0.55)",
                        fontFamily: "'JetBrains Mono', monospace", marginBottom: 8 }}>
            {stats.mount_path ?? "drive"}
          </div>

          <StackedBar stats={stats} />

          <div style={{ display: "flex", gap: 14, fontSize: 12, marginTop: 8,
                        color: "rgba(255,255,255,0.7)", flexWrap: "wrap" }}>
            <Legend color="rgba(255,255,255,0.18)" label={`reserved ${fmtGB(stats.reserved)}`} />
            <Legend color="#9bf2c0" label={`pinned ${fmtGB(stats.pinned_bytes)}`} />
            <Legend color="#5be7ff" label={`streamed ${fmtGB(stats.streamed_bytes)}`} />
            <Legend color="rgba(255,255,255,0.10)" label={`free ${fmtGB(stats.free)}`} />
          </div>

          <div style={{ display: "flex", gap: 14, fontSize: 12, marginTop: 6,
                        color: "rgba(255,255,255,0.55)" }}>
            <span>Total {fmtGB(stats.capacity)}</span>
            <span>· Used {fmtGB(stats.capacity - stats.free)}</span>
            <span>· Free {fmtGB(stats.free)}</span>
          </div>

          <div style={{ marginTop: 10 }}>
            <button
              disabled={busy}
              onClick={onClear}
              style={{
                padding: "10px 14px", minHeight: 44,
                background: "rgba(255,255,255,0.10)", color: "#fff",
                border: "1px solid rgba(255,255,255,0.18)", borderRadius: 999,
                fontWeight: 700, fontSize: 13, letterSpacing: "0.06em",
                cursor: "pointer",
                opacity: busy ? 0.6 : 1,
              }}
            >{busy ? "Clearing…" : "Clear streamed cache"}</button>
            {msg && <span style={{ marginLeft: 10, fontSize: 13, color: "#9bf2c0" }}>{msg}</span>}
          </div>
        </>
      )}
    </div>
  );
}

function StackedBar({ stats }: { stats: NonNullable<ReturnType<typeof useCacheStats>> }) {
  const cap = Math.max(1, stats.capacity);
  const reserved = (stats.reserved / cap) * 100;
  const pinned   = (stats.pinned_bytes / cap) * 100;
  const streamed = (stats.streamed_bytes / cap) * 100;
  const free     = Math.max(0, 100 - reserved - pinned - streamed);
  return (
    <div style={{
      display: "flex", width: "100%", height: 14, borderRadius: 7,
      overflow: "hidden", background: "rgba(255,255,255,0.06)",
      border: "1px solid rgba(255,255,255,0.10)",
    }}>
      <span data-cache-seg="reserved" style={{ width: `${reserved}%`, background: "rgba(255,255,255,0.18)" }}/>
      <span data-cache-seg="pinned"   style={{ width: `${pinned}%`,   background: "#9bf2c0" }}/>
      <span data-cache-seg="streamed" style={{ width: `${streamed}%`, background: "#5be7ff" }}/>
      <span data-cache-seg="free"     style={{ width: `${free}%`,     background: "rgba(255,255,255,0.10)" }}/>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 10, height: 10, borderRadius: 2, background: color, border: "1px solid rgba(0,0,0,0.2)" }}/>
      {label}
    </span>
  );
}
