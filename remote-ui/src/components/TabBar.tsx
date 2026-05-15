import type { ReactNode } from "react";

export type Tab = "now" | "files" | "playlists" | "search";

const TABS: { id: Tab; label: string; icon: ReactNode }[] = [
  { id: "now",       label: "Now",       icon: "▶" },
  { id: "files",     label: "Files",     icon: "📁" },
  { id: "playlists", label: "Playlists", icon: "≡" },
  { id: "search",    label: "Search",    icon: "⌕" },
];

/** Fixed-position bottom nav. Phones with home-indicator safe-area get
 *  the env() padding from index.css. */
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
              flex: 1, display: "flex", flexDirection: "column",
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
