import { useEffect, useState } from "react";

export function RecordIndicator() {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { on: boolean };
      setOn(detail.on);
    };
    window.addEventListener("boombox:record", handler as EventListener);
    return () => window.removeEventListener("boombox:record", handler as EventListener);
  }, []);
  if (!on) return null;
  return (
    <div style={{
      position: "fixed", top: 12, right: 12, zIndex: 9997,
      display: "flex", alignItems: "center", gap: 6,
      background: "rgba(0,0,0,0.6)", padding: "4px 10px", borderRadius: 12,
      color: "white", fontSize: 14, fontWeight: 600,
    }}>
      <span style={{
        width: 10, height: 10, background: "red", borderRadius: "50%",
        animation: "rec-pulse 1.2s infinite",
      }} />
      REC
      <style>{`@keyframes rec-pulse { 0%,100% { opacity: 1 } 50% { opacity: 0.3 } }`}</style>
    </div>
  );
}
