// SeekableBar — a touch-friendly wrapper around a skin's progress bar.
//
// The visual bar can be as thin as the skin wants (12 px in design, ~7 px on
// the 5″ screen) but the actual touch hit-area extends 22 px above and below
// it via padding so dragging is comfortable on the touchscreen. Tap to jump,
// drag to scrub.
//
// While dragging we render the position the user's finger maps to, even
// before Mopidy accepts the seek; the parent's optimistic positionMs update
// keeps the rest of the UI in sync.

import { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

type Props = {
  /** 0..1 progress through the track. */
  value: number;
  /** Track length in seconds (used to convert tap position → seek). */
  lengthSec: number;
  /** Called with seconds-into-track when the user taps or finishes a drag. */
  onSeek?: (sec: number) => void;
  /** Hit-area height in design pixels. Default 56 (≈ 34 px on 800×480). */
  hitHeight?: number;
  /** Visual content (the actual bar markup). */
  children: ReactNode;
  /** Optional style passed to the outer wrapper. */
  style?: CSSProperties;
};

export function SeekableBar({ value, lengthSec, onSeek, hitHeight = 56, children, style }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [draggingFraction, setDraggingFraction] = useState<number | null>(null);
  const dragging = useRef(false);

  const fractionFromEvent = (clientX: number): number => {
    const el = ref.current;
    if (!el) return 0;
    const r = el.getBoundingClientRect();
    if (r.width <= 0) return 0;
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width));
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (!onSeek || lengthSec <= 0) return;
    e.stopPropagation();
    dragging.current = true;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    const f = fractionFromEvent(e.clientX);
    setDraggingFraction(f);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    e.stopPropagation();
    setDraggingFraction(fractionFromEvent(e.clientX));
  };

  const finish = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    dragging.current = false;
    try { (e.target as Element).releasePointerCapture?.(e.pointerId); } catch { /* noop */ }
    if (draggingFraction !== null && onSeek) {
      onSeek(draggingFraction * lengthSec);
    }
    setDraggingFraction(null);
  };

  // Reset drag state if props change underneath us.
  useEffect(() => () => { dragging.current = false; }, []);

  const interactive = !!onSeek && lengthSec > 0;
  const displayed = draggingFraction ?? value;

  return (
    <div
      ref={ref}
      onPointerDown={interactive ? onPointerDown : undefined}
      onPointerMove={interactive ? onPointerMove : undefined}
      onPointerUp={interactive ? finish : undefined}
      onPointerCancel={interactive ? finish : undefined}
      data-progress={displayed}
      style={{
        position: "relative",
        // Bigger hit area than the visual bar — improves touch accuracy.
        padding: `${hitHeight / 2}px 0`,
        marginTop: -hitHeight / 2,
        marginBottom: -hitHeight / 2,
        cursor: interactive ? "pointer" : "default",
        touchAction: "none",
        userSelect: "none",
        ...style,
      }}
    >
      {/* The skin's visual bar lives inside, with a CSS variable so the skin
       * can render against the (possibly drag-overridden) value. */}
      <div style={{ ["--seek-fraction" as string]: displayed.toFixed(4) }}>
        {children}
      </div>
    </div>
  );
}
