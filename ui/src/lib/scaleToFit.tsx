import { useEffect, useState } from "react";
import type { ReactNode } from "react";

/**
 * Wraps a fixed-size design (e.g. 1280×800) and scales it to fit the viewport
 * while preserving aspect ratio. Centered, letterboxed if the aspect mismatches.
 *
 * Implementation note: we use absolute positioning with
 * `translate(-50%, -50%) scale(s)` because grid/flex centering does NOT center
 * oversized children — the layout engine sizes the track to the child, and the
 * scale-around-center math then offsets visually. Absolute centering of the
 * unscaled box, plus `transform-origin: center center`, gives proper letterbox.
 */
export function ScaleToFit({
  width = 1280,
  height = 800,
  background = "#000",
  children,
}: {
  width?: number;
  height?: number;
  background?: string;
  children: ReactNode;
}) {
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const recalc = () => {
      const sx = window.innerWidth / width;
      const sy = window.innerHeight / height;
      setScale(Math.min(sx, sy));
    };
    recalc();
    window.addEventListener("resize", recalc);
    return () => window.removeEventListener("resize", recalc);
  }, [width, height]);

  return (
    <div style={{
      position: "fixed",
      inset: 0,
      background,
      overflow: "hidden",
    }}>
      <div style={{
        position: "absolute",
        top: "50%",
        left: "50%",
        width,
        height,
        transform: `translate(-50%, -50%) scale(${scale})`,
        transformOrigin: "center center",
      }}>
        {children}
      </div>
    </div>
  );
}
