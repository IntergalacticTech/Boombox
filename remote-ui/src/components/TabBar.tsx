import type { Route } from "../lib/route";

export type Tab = "now" | "music" | "video" | "search" | "more";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "now",    label: "Now",    icon: "▶" },
  { id: "music",  label: "Music",  icon: "♫" },
  { id: "video",  label: "Video",  icon: "🎬" },
  { id: "search", label: "Search", icon: "⌕" },
  { id: "more",   label: "More",   icon: "⋯" },
];

/** Which tab lights up for a route: Playlists, Files and Admin live under More. */
export function tabForRoute(route: Route): Tab {
  return route === "now" || route === "music" || route === "video" || route === "search"
    ? route : "more";
}

/** Phone bottom nav (< 900 px). Home-indicator phones get the safe-area inset. */
export function TabBar(
  { active, onChange }: { active: Tab; onChange: (t: Tab) => void },
) {
  return (
    <nav
      aria-label="Primary"
      style={{
        position: "fixed", left: 0, right: 0, bottom: 0,
        display: "flex", justifyContent: "space-around",
        background: "var(--panel)", borderTop: "1px solid var(--rule)",
        paddingBottom: "max(8px, env(safe-area-inset-bottom))",
        paddingTop: 8, zIndex: 10,
      }}
    >
      {TABS.map((t) => {
        const selected = t.id === active;
        return (
          <button
            key={t.id}
            type="button"
            aria-pressed={selected}
            aria-label={t.label}
            onClick={() => onChange(t.id)}
            style={{
              flex: 1, minWidth: 0, display: "flex", flexDirection: "column",
              alignItems: "center", gap: 2,
              padding: "6px 4px", border: 0, background: "transparent",
              color: selected ? "var(--accent)" : "var(--ink2)",
              fontSize: 11, cursor: "pointer",
            }}
          >
            <span style={{ fontSize: 22, lineHeight: 1 }}>{t.icon}</span>
            <span>{t.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
