// QueuePill — small persistent pill at top-center of the screen showing the
// current queue length and opening the QueueDrawer when tapped.
//
// Companion to SourceSwitcher (top-left) and SkinPicker (top-right). Together
// they form a symmetric trio of always-visible touch entry points.

import { useEffect, useRef, useState } from "react";
import { getQueue } from "./library";
import { QueueDrawer } from "./QueueDrawer";

export function QueuePill() {
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState<number | null>(null);
  const aborted = useRef(false);

  useEffect(() => {
    aborted.current = false;
    const tick = async () => {
      try {
        const q = await getQueue();
        if (!aborted.current) setCount(q.length);
      } catch {
        if (!aborted.current) setCount(null);
      }
    };
    tick();
    // Refresh every 4s normally; the drawer itself polls more aggressively
    // when open, so we don't compete.
    const id = setInterval(tick, 4000);
    return () => { aborted.current = true; clearInterval(id); };
  }, []);

  return (
    <>
      <button
        onPointerDown={(e) => e.stopPropagation()}
        onPointerUp={(e) => e.stopPropagation()}
        onClick={() => setOpen(true)}
        style={{
          position: "fixed",
          top: 8,
          left: "50%",
          transform: "translateX(-50%)",
          padding: "6px 12px",
          background: "rgba(0,0,0,0.7)",
          color: "#fff",
          border: "1px solid rgba(255,255,255,0.2)",
          borderRadius: 999,
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
          letterSpacing: "0.16em",
          cursor: "pointer",
          zIndex: 1000,
          backdropFilter: "blur(8px)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        QUEUE · {count === null ? "—" : count}
      </button>
      {open && <QueueDrawer onClose={() => setOpen(false)} />}
    </>
  );
}
