import type { CSSProperties } from "react";
import type { Route } from "../lib/route";

const SECTIONS: { route: Route; label: string; icon: string }[] = [
  { route: "now",       label: "Now playing", icon: "▶" },
  { route: "music",     label: "Music",       icon: "♫" },
  { route: "video",     label: "Video",       icon: "🎬" },
  { route: "search",    label: "Search",      icon: "⌕" },
  { route: "playlists", label: "Playlists",   icon: "≡" },
  { route: "files",     label: "Files",       icon: "📁" },
];

const itemStyle = (active: boolean): CSSProperties => ({
  display: "flex", alignItems: "center", gap: 10, width: "100%",
  padding: "10px 12px", borderRadius: 10, border: 0, textAlign: "left",
  background: active ? "rgba(139,92,246,0.16)" : "transparent",
  color: active ? "var(--ink)" : "var(--ink2)", fontSize: 15, cursor: "pointer",
});

/** Desktop (≥ 900 px) navigation: every section, then Admin, then Settings. */
export function Sidebar({ active, onNavigate, onOpenSettings, adminLocked = true }: {
  active: Route;
  onNavigate: (r: Route) => void;
  onOpenSettings: () => void;
  adminLocked?: boolean;
}) {
  const item = (route: Route, label: string, icon: string) => (
    <button key={route} type="button" onClick={() => onNavigate(route)}
            aria-current={active === route ? "page" : undefined}
            style={itemStyle(active === route)}>
      <span aria-hidden="true" style={{ width: 22, textAlign: "center" }}>{icon}</span>
      {label}
    </button>
  );
  return (
    <nav aria-label="Sections" style={{
      borderRight: "1px solid var(--rule)", background: "var(--panel)",
      padding: "16px 10px", display: "flex", flexDirection: "column", gap: 4,
      overflowY: "auto", minWidth: 0,
    }}>
      <div style={{ fontWeight: 800, fontSize: 18, padding: "4px 12px 12px" }}>Boombox</div>
      {SECTIONS.map((s) => item(s.route, s.label, s.icon))}
      <div style={{ margin: "16px 12px 4px", fontSize: 11, textTransform: "uppercase",
                    letterSpacing: "0.08em", color: "var(--ink2)" }}>Admin</div>
      {item("accounts", "Accounts", adminLocked ? "🔒" : "🔓")}
      <div style={{ flex: 1 }} />
      <button type="button" onClick={onOpenSettings} style={itemStyle(false)}>
        <span aria-hidden="true" style={{ width: 22, textAlign: "center" }}>⚙</span>
        Settings
      </button>
    </nav>
  );
}
