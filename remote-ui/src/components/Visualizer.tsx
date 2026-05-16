import { useEffect, useRef, useState } from "react";

// 64 bins of log-scaled magnitude per frame, courtesy of boombox-audio.
// Numbers are in 0..1. Anything else is a malformed frame and we drop it.
interface Frame { bins: number[]; }

/** Live spectrum bars driven by boombox-audio's /audio/ws feed. Only
 *  renders when `playing` is true, both because the bins are noisy
 *  during silence and because keeping a WS open on a sleeping phone is
 *  wasteful. Auto-reconnects on close with a 2 s backoff — the audio
 *  feed is best-effort decoration, not load-bearing UI. */
export function Visualizer(
  { base, enabled }: { base: string; enabled: boolean },
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const binsRef = useRef<number[]>(new Array(64).fill(0));
  const [connected, setConnected] = useState(false);

  // WS lifecycle — connect when enabled flips on, tear down when off.
  useEffect(() => {
    if (!enabled) return;
    const wsUrl = base.replace(/^http/, "ws").replace(/\/$/, "") + "/audio/ws";
    let ws: WebSocket | null = null;
    let killed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const open = () => {
      ws = new WebSocket(wsUrl);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data) as Frame;
          if (Array.isArray(msg?.bins)) binsRef.current = msg.bins;
        } catch { /* drop */ }
      };
      ws.onclose = () => {
        setConnected(false);
        if (killed) return;
        retry = setTimeout(open, 2000);
      };
      ws.onerror = () => { /* onclose owns the reconnect */ };
    };
    open();
    return () => {
      killed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, [base, enabled]);

  // Render loop — pulls the latest bins on each animation frame and
  // paints. Decays toward zero between frames so a brief WS hiccup
  // doesn't freeze the bars at their last-known height.
  useEffect(() => {
    if (!enabled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    const draw = () => {
      const { width, height } = canvas.getBoundingClientRect();
      // Scale to device pixels so the bars stay crisp on hi-DPI phones.
      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
      ctx.clearRect(0, 0, width, height);

      const bins = binsRef.current;
      const n = bins.length || 1;
      const barW = width / n;
      const gap = Math.max(1, barW * 0.2);
      const accent = getComputedStyle(canvas)
        .getPropertyValue("--accent").trim() || "#8b5cf6";
      ctx.fillStyle = accent;

      for (let i = 0; i < n; i++) {
        const v = Math.max(0, Math.min(1, bins[i] || 0));
        const h = v * height;
        ctx.fillRect(i * barW + gap / 2, height - h,
                     Math.max(1, barW - gap), h);
        // Gentle decay so frame drops don't leave bars stuck up.
        bins[i] = v * 0.85;
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [enabled]);

  if (!enabled) return null;
  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      title={connected ? "live spectrum" : "connecting…"}
      style={{
        width: "100%", height: 48, display: "block",
        opacity: connected ? 0.9 : 0.3,
        transition: "opacity 0.4s ease",
      }}
    />
  );
}
