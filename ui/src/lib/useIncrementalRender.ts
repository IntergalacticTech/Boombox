// Incremental rendering for very large lists.
//
// Rendering 8 k+ album cards at once locks the UI thread for 1-3 seconds
// on the Pi touchscreen and chews ~120 MB of DOM. IntersectionObserver
// lets us render an initial slice and grow it as the user scrolls — no
// dependency on react-window, no layout assumptions, no item-height
// math.
//
// Usage:
//   const { visible, sentinelRef } = useIncrementalRender(items.length, 80, 80);
//   {items.slice(0, visible).map(...)}
//   <div ref={sentinelRef} />

import { useEffect, useRef, useState } from "react";

export function useIncrementalRender(
  total: number,
  initial: number = 100,
  step: number = 100,
) {
  const [visible, setVisible] = useState(() => Math.min(total, initial));
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // Reset when the source list changes (e.g. user navigated to a
  // different directory). Without this, switching from a 9 k-album list
  // back to a 6-item playlist list would carry over a stale `visible` of
  // 100 and render nothing past the actual list length — harmless, but
  // also we'd never re-cap when the user comes back.
  useEffect(() => {
    setVisible(Math.min(total, initial));
  }, [total, initial]);

  useEffect(() => {
    if (visible >= total) return;
    const el = sentinelRef.current;
    if (!el) return;
    // rootMargin pre-fetches a screen ahead so the user never sees a
    // blank gap while the next batch mounts. 400 px is roughly two more
    // grid rows on a 140 px album thumb.
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setVisible((v) => Math.min(total, v + step));
          }
        }
      },
      { rootMargin: "400px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [visible, total, step]);

  return { visible, sentinelRef };
}
