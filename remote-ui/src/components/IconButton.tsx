import type { ReactNode } from "react";

/** A round, themed touch button. `primary` makes it larger + accent-filled
 *  (used for play/pause); `toggled` paints the accent for stateful toggles
 *  like shuffle/repeat; the rest are outline buttons. */
export function IconButton(
  { label, onClick, children,
    disabled = false, primary = false, toggled = false }: {
    label: string;
    onClick: () => void;
    children: ReactNode;
    disabled?: boolean;
    primary?: boolean;
    toggled?: boolean;
  },
) {
  const size = primary ? 72 : 56;
  const filled = primary || toggled;
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={toggled || undefined}
      onClick={onClick}
      disabled={disabled}
      data-primary={primary}
      data-toggled={toggled}
      style={{
        width: size, height: size, borderRadius: "50%",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        fontSize: primary ? 28 : 22, lineHeight: 1,
        border: filled ? 0 : "1px solid var(--rule)",
        background: filled ? "var(--accent)" : "var(--panel)",
        color: filled ? "var(--bg)" : "var(--ink)",
        opacity: disabled ? 0.4 : 1,
        cursor: disabled ? "default" : "pointer",
        flexShrink: 0,
      }}
    >
      {children}
    </button>
  );
}
