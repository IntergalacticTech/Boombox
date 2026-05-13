import { useEffect, useState } from "react";

const COPY: Record<string, { title: string; body: string }> = {
  airplay:  { title: "AirPlay", body: "Tap the AirPlay icon on your iPhone, iPad, or Mac and pick \"Boombox\"." },
  spotify:  { title: "Spotify", body: "Open Spotify on any device, tap Devices, and pick \"Boombox\"." },
  bluetooth:{ title: "Bluetooth", body: "Pairing is open for 60 seconds. Pair your phone to \"Boombox\"." },
};

export function SourceInstructionOverlay() {
  const [source, setSource] = useState<string | null>(null);
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { source: string };
      setSource(detail.source);
      setTimeout(() => setSource(null), 5000);
    };
    window.addEventListener("boombox:source-overlay", handler as EventListener);
    return () => window.removeEventListener("boombox:source-overlay", handler as EventListener);
  }, []);
  if (!source || !COPY[source]) return null;
  const { title, body } = COPY[source];
  return (
    <div onClick={() => setSource(null)} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)", color: "white",
      display: "grid", placeItems: "center", zIndex: 9998, padding: 32,
    }}>
      <div style={{ textAlign: "center", maxWidth: 640 }}>
        <div style={{ fontSize: 36, fontWeight: 700, marginBottom: 16 }}>{title}</div>
        <div style={{ fontSize: 20, lineHeight: 1.4 }}>{body}</div>
      </div>
    </div>
  );
}
