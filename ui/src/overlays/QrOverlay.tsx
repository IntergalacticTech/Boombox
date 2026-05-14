import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

export function QrOverlay() {
  const [visible, setVisible] = useState(false);
  const [info, setInfo] = useState<{ url: string; user: string; pin: string } | null>(null);

  useEffect(() => {
    const onShow = async () => {
      try {
        const r = await fetch("/api/upload/enable", { method: "POST" });
        const body = await r.json();
        setInfo({
          url: body.url ?? `http://${location.hostname}:8090/`,
          user: body.user ?? "boombox",
          pin: body.pin ?? "—",
        });
      } catch {
        setInfo({ url: `http://${location.hostname}:8090/`, user: "boombox", pin: "—" });
      }
      setVisible(v => !v);
    };
    window.addEventListener("boombox:web-qr", onShow as EventListener);
    return () => window.removeEventListener("boombox:web-qr", onShow as EventListener);
  }, []);

  if (!visible || !info) return null;
  const value = `${info.url}#user=${info.user}&pin=${info.pin}`;
  return (
    <div onClick={() => setVisible(false)} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.92)", color: "white",
      display: "grid", placeItems: "center", zIndex: 9999,
    }}>
      <div style={{ display: "grid", gap: 12, placeItems: "center" }}>
        <div style={{ background: "white", padding: 16 }}>
          <QRCodeSVG value={value} size={320} />
        </div>
        <div style={{ fontSize: 18 }}>{info.url}</div>
        <div style={{ fontSize: 14, opacity: 0.7 }}>user: {info.user}  pin: {info.pin}</div>
        <div style={{ fontSize: 12, opacity: 0.5 }}>tap to dismiss</div>
      </div>
    </div>
  );
}
