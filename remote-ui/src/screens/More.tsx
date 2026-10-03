import type { CSSProperties } from "react";
import type { Navigate } from "../lib/route";

const rowStyle: CSSProperties = {
  display: "flex", alignItems: "center", gap: 12, width: "100%", minHeight: 52,
  padding: "12px 8px", border: 0, borderBottom: "1px solid var(--rule)",
  background: "transparent", color: "var(--ink)", fontSize: 16, cursor: "pointer",
  textAlign: "left",
};

/** The phone's More tab: Playlists, Files, Admin → Accounts / Storage, Settings. */
export function More({ navigate, onOpenSettings, adminLocked = true }: {
  navigate: Navigate; onOpenSettings: () => void; adminLocked?: boolean;
}) {
  const rows: { label: string; icon: string; hint?: string; onClick: () => void }[] = [
    { label: "Playlists", icon: "≡", onClick: () => navigate("playlists") },
    { label: "Files", icon: "📁", onClick: () => navigate("files") },
    { label: "Accounts", icon: adminLocked ? "🔒" : "🔓", hint: "Admin",
      onClick: () => navigate("accounts") },
    { label: "Storage", icon: adminLocked ? "🔒" : "🔓", hint: "Admin",
      onClick: () => navigate("storage") },
    { label: "Settings", icon: "⚙", onClick: onOpenSettings },
  ];
  return (
    <div style={{ padding: 16, paddingBottom: 96 }}>
      <h1 style={{ fontSize: 22, margin: "0 0 12px" }}>More</h1>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {rows.map((r) => (
          <li key={r.label}>
            <button type="button" onClick={r.onClick} style={rowStyle}>
              <span aria-hidden="true" style={{ width: 24, textAlign: "center" }}>{r.icon}</span>
              <span style={{ flex: 1 }}>{r.label}</span>
              {r.hint && <span aria-hidden="true" style={{ fontSize: 12, color: "var(--ink2)" }}>
                {r.hint}</span>}
              <span aria-hidden="true" style={{ color: "var(--ink2)" }}>›</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
