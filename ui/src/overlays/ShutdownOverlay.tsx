import { useEffect, useState } from "react";

export function ShutdownOverlay() {
  const [seconds, setSeconds] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    let timer: number | undefined;
    const onCountdown = (e: Event) => {
      const detail = (e as CustomEvent).detail as { seconds: number };
      setSeconds(detail.seconds);
      let s = detail.seconds;
      timer = window.setInterval(() => {
        s -= 1;
        if (s <= 0) { window.clearInterval(timer); setSeconds(0); }
        else setSeconds(s);
      }, 1000);
    };
    const onConfirm = () => { setConfirmed(true); window.clearInterval(timer); };
    window.addEventListener("boombox:shutdown-countdown", onCountdown as EventListener);
    window.addEventListener("boombox:shutdown-confirm", onConfirm);
    return () => {
      window.removeEventListener("boombox:shutdown-countdown", onCountdown as EventListener);
      window.removeEventListener("boombox:shutdown-confirm", onConfirm);
      window.clearInterval(timer);
    };
  }, []);
  if (seconds == null) return null;
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.9)", color: "white",
      display: "grid", placeItems: "center", zIndex: 10000, fontSize: 48, fontWeight: 700,
    }}>
      {confirmed ? "Shutting down…" : `Power off in ${seconds}s — release to cancel`}
    </div>
  );
}
