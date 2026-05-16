/** Subtle pulse skeleton for list rows during a fetch. Renders N
 *  placeholder rows that match the list's row height so layout doesn't
 *  jump when real data lands. The pulse is a CSS keyframe declared
 *  inline (no @keyframes registration needed — the browser DOM
 *  accepts a single rule via a one-shot <style> on mount). */
import { useEffect } from "react";

const PULSE_NAME = "bbx-skel-pulse";

export function SkeletonRows({ count = 6 }: { count?: number }) {
  useEffect(() => {
    if (document.getElementById(PULSE_NAME)) return;
    const s = document.createElement("style");
    s.id = PULSE_NAME;
    s.textContent = `@keyframes ${PULSE_NAME} {
      0%, 100% { opacity: 0.45; }
      50%      { opacity: 0.75; }
    }`;
    document.head.appendChild(s);
  }, []);
  return (
    <ul aria-busy="true" aria-label="Loading"
        style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {Array.from({ length: count }).map((_, i) => (
        <li key={i} style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "10px 4px", borderBottom: "1px solid var(--rule)",
        }}>
          <div style={{
            flex: 1, minWidth: 0, display: "flex",
            flexDirection: "column", gap: 4,
          }}>
            <div style={{
              height: 14, width: `${60 + ((i * 13) % 30)}%`,
              borderRadius: 4, background: "var(--panel)",
              animation: `${PULSE_NAME} 1.4s ease-in-out infinite`,
            }} />
            <div style={{
              height: 10, width: `${30 + ((i * 7) % 30)}%`,
              borderRadius: 4, background: "var(--panel)",
              animation: `${PULSE_NAME} 1.4s ease-in-out infinite`,
              animationDelay: "0.2s",
            }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
