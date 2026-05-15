import type { ReactNode } from "react";

/** A round, themed touch button. `primary` makes it larger + accent-filled
 *  (used for play/pause); the rest are outline buttons. */
export function IconButton(
  { label, onClick, children, disabled = false, primary = false }: {
    label: string;
    onClick: () => void;
    children: ReactNode;
    disabled?: boolean;
    primary?: boolean;
  },
) {
  const size = primary ? 72 : 56;
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      data-primary={primary}
      style={{
        width: size, height: size, borderRadius: "50%",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        fontSize: primary ? 28 : 22, lineHeight: 1,
        border: primary ? 0 : "1px solid var(--rule)",
        background: primary ? "var(--accent)" : "var(--panel)",
        color: primary ? "var(--bg)" : "var(--ink)",
        opacity: disabled ? 0.4 : 1,
        cursor: disabled ? "default" : "pointer",
        flexShrink: 0,
      }}
    >
      {children}
    </button>
  );
}
