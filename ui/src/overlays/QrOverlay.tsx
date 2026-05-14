import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

export function QrOverlay() {
  const [visible, setVisible] = useState(false);
  const [url, setUrl] = useState<string>("");

  useEffect(() => {
    const onShow = async () => {
      // Turning on remote access is best-effort — the QR is still useful
      // even if the enable call fails (the user can toggle it in Settings).
      try {
        await fetch("/api/remote/admin/enable", { method: "POST" });
      } catch { /* ignore */ }
      setUrl(`http://${location.hostname}:8090/remote/`);
      setVisible(v => !v);
    };
    window.addEventListener("boombox:web-qr", onShow as EventListener);
    return () => window.removeEventListener("boombox:web-qr", onShow as EventListener);
  }, []);

  if (!visible || !url) return null;
  return (
    <div onClick={() => setVisible(false)} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.92)", color: "white",
      display: "grid", placeItems: "center", zIndex: 9999,
    }}>
      <div style={{ display: "grid", gap: 12, placeItems: "center" }}>
        <div style={{ background: "white", padding: 16 }}>
          <QRCodeSVG value={url} size={320} />
        </div>
        <div style={{ fontSize: 18 }}>{url}</div>
        <div style={{ fontSize: 14, opacity: 0.7 }}>
          open on your phone, then pair with the PIN from Settings
        </div>
        <div style={{ fontSize: 12, opacity: 0.5 }}>tap to dismiss</div>
      </div>
    </div>
  );
}
