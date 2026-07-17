import type { CSSProperties, ReactNode } from "react";

// Shared, touch-friendly primitives. Everything uses the remote-ui CSS
// variable palette (--bg / --panel / --ink / --ink2 / --accent / --rule) so
// the wizard reads as part of the same product. Min touch target 44px.

export const inputStyle: CSSProperties = {
  padding: "13px 14px", borderRadius: 10, minHeight: 48, width: "100%",
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", fontSize: 17,
};

export function PrimaryButton(
  props: React.ButtonHTMLAttributes<HTMLButtonElement>,
) {
  const { style, disabled, ...rest } = props;
  return (
    <button
      {...rest}
      disabled={disabled}
      style={{
        padding: "14px 18px", borderRadius: 12, border: 0, minHeight: 48,
        background: "var(--accent)", color: "var(--bg)",
        fontSize: 16, fontWeight: 700, cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.5 : 1, width: "100%",
        ...style,
      }}
    />
  );
}

export function SecondaryButton(
  props: React.ButtonHTMLAttributes<HTMLButtonElement>,
) {
  const { style, disabled, ...rest } = props;
  return (
    <button
      {...rest}
      disabled={disabled}
      style={{
        padding: "13px 18px", borderRadius: 12, minHeight: 48,
        border: "1px solid var(--rule)", background: "var(--panel)",
        color: "var(--ink)", fontSize: 15, cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.5 : 1, width: "100%",
        ...style,
      }}
    />
  );
}

export function Field(
  { label, children }: { label: string; children: ReactNode },
) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 13, color: "var(--ink2)" }}>{label}</span>
      {children}
    </label>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <div role="alert" style={{ color: "#ff7878", fontSize: 14 }}>
      {children}
    </div>
  );
}

export function Card(
  { selected, onClick, children }:
  { selected?: boolean; onClick?: () => void; children: ReactNode },
) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "block", width: "100%", textAlign: "left", cursor: "pointer",
        padding: 16, borderRadius: 12, minHeight: 48,
        border: `1px solid ${selected ? "var(--accent)" : "var(--rule)"}`,
        background: selected ? "rgba(139,92,246,0.12)" : "var(--panel)",
        color: "var(--ink)",
      }}
    >
      {children}
    </button>
  );
}

/** Top progress indicator: dots for each step, current one accented. */
export function Stepper({ step, total }: { step: number; total: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div role="progressbar" aria-valuenow={step + 1} aria-valuemin={1}
           aria-valuemax={total}
           style={{ display: "flex", gap: 6, justifyContent: "center" }}>
        {Array.from({ length: total }, (_, i) => (
          <span key={i} style={{
            width: i === step ? 22 : 8, height: 8, borderRadius: 4,
            background: i <= step ? "var(--accent)" : "var(--rule)",
            transition: "width 0.2s ease",
          }} />
        ))}
      </div>
      <div style={{ textAlign: "center", fontSize: 12, color: "var(--ink2)" }}>
        Step {step + 1} of {total}
      </div>
    </div>
  );
}

/** Centered, single-column layout capped at ~560px — legible at 800×480 and
 *  on a phone. */
export function Shell({ children }: { children: ReactNode }) {
  return (
    <div style={{
      minHeight: "100%", display: "flex", justifyContent: "center",
      padding: "24px 20px 40px",
    }}>
      <div style={{
        width: "100%", maxWidth: 560, display: "flex",
        flexDirection: "column", gap: 20,
      }}>
        {children}
      </div>
    </div>
  );
}

export function StepBody(
  { title, subtitle, children }:
  { title: string; subtitle?: ReactNode; children?: ReactNode },
) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 style={{ fontSize: 26, margin: 0, lineHeight: 1.15 }}>{title}</h1>
        {subtitle && (
          <p style={{ color: "var(--ink2)", margin: 0, fontSize: 15 }}>
            {subtitle}
          </p>
        )}
      </div>
      {children}
    </div>
  );
}

/** Back / Next (or custom primary) footer row. */
export function NavRow(
  { onBack, primary, secondary }:
  { onBack?: () => void; primary?: ReactNode; secondary?: ReactNode },
) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {primary}
      {secondary}
      {onBack && (
        <button type="button" onClick={onBack} style={{
          background: "none", border: 0, color: "var(--ink2)",
          fontSize: 14, cursor: "pointer", padding: "8px 0",
        }}>← Back</button>
      )}
    </div>
  );
}
