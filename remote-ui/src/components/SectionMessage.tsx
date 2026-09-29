/** The one way a section says "can't show this right now": a message, an
 *  optional hint, and Retry. Used for library down, video server not set
 *  up, kiosk not signed in, and sections not available yet. */
export function SectionMessage({ title, message, hint, onRetry }: {
  title?: string; message: string; hint?: string; onRetry?: () => void;
}) {
  return (
    <div role="status" style={{
      padding: 24, textAlign: "center", color: "var(--ink2)",
      display: "flex", flexDirection: "column", gap: 10, alignItems: "center",
    }}>
      {title && <h2 style={{ margin: 0, color: "var(--ink)", fontSize: 18 }}>{title}</h2>}
      <p style={{ margin: 0 }}>{message}</p>
      {hint && <p style={{ margin: 0, fontSize: 13 }}>{hint}</p>}
      {onRetry && (
        <button type="button" onClick={onRetry} style={{
          padding: "10px 18px", borderRadius: 10, border: "1px solid var(--rule)",
          background: "var(--panel)", color: "var(--ink)", fontSize: 15, cursor: "pointer",
        }}>Retry</button>
      )}
    </div>
  );
}
