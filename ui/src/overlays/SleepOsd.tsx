import { useEffect, useState } from "react";

export function SleepOsd() {
  const [mins, setMins] = useState<number | null>(null);
  useEffect(() => {
    let timer: number | undefined;
    const onTimer = (e: Event) => {
      const detail = (e as CustomEvent).detail as { minutes: number | null };
      setMins(detail.minutes);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setMins(prev => prev), 2000); // OSD stays visible
    };
    const onExpired = () => setMins(null);
    window.addEventListener("boombox:sleep-timer", onTimer as EventListener);
    window.addEventListener("boombox:sleep-expired", onExpired);
    return () => {
      window.removeEventListener("boombox:sleep-timer", onTimer as EventListener);
      window.removeEventListener("boombox:sleep-expired", onExpired);
    };
  }, []);
  if (mins == null) return null;
  return (
    <div style={{
      position: "fixed", top: 24, left: "50%", transform: "translateX(-50%)",
      background: "rgba(0,0,0,0.8)", color: "white", padding: "8px 16px",
      borderRadius: 12, fontSize: 16, zIndex: 9998,
    }}>
      Sleep: {mins} min
    </div>
  );
}
