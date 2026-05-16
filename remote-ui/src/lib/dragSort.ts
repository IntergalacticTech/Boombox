// Pointer-driven list reorder. Works on touch and mouse with a single
// code path because pointer events normalise both. The caller wires up
// a tiny `useDragSort` hook on each row and we resolve the drop target
// by counting how many rows the pointer has crossed since pointerdown.
//
// We deliberately avoid HTML5 drag-and-drop — it's flaky on mobile,
// requires a setData dance, and doesn't play well with React state.

import { useCallback, useEffect, useRef, useState } from "react";

interface DragState {
  fromIndex: number;
  pointerY: number;
  rowHeight: number;
}

export interface DragSortApi {
  /** Bind to the *handle* element (a small grip / icon). The whole row
   *  doesn't need to be the handle — keeping it on a handle preserves
   *  tap-to-jump on the row body. */
  handleProps: (index: number) => {
    onPointerDown: (e: React.PointerEvent) => void;
    style: React.CSSProperties;
  };
  /** Style to apply to each row so the actively-dragged one floats and
   *  the displaced rows shift visually. */
  rowStyle: (index: number) => React.CSSProperties;
  /** True while a drag is in flight (caller can dim other UI, etc). */
  dragging: boolean;
}

/** Hook factory: pass the current item count and an onMove(from, to)
 *  commit callback. */
export function useDragSort(
  itemCount: number,
  onMove: (from: number, to: number) => void,
): DragSortApi {
  const [state, setState] = useState<DragState | null>(null);
  const stateRef = useRef<DragState | null>(null);
  stateRef.current = state;

  // The vertical offset of the dragged row from its original position.
  const [dy, setDy] = useState(0);
  const dyRef = useRef(0);
  dyRef.current = dy;

  const settle = useCallback(() => {
    const s = stateRef.current;
    const offset = dyRef.current;
    setState(null);
    setDy(0);
    if (!s || !s.rowHeight) return;
    const shift = Math.round(offset / s.rowHeight);
    const target = Math.max(0, Math.min(itemCount - 1, s.fromIndex + shift));
    if (target !== s.fromIndex) onMove(s.fromIndex, target);
  }, [itemCount, onMove]);

  useEffect(() => {
    if (!state) return;
    const onMove = (e: PointerEvent) => {
      const s = stateRef.current;
      if (!s) return;
      setDy(e.clientY - s.pointerY);
    };
    const onUp = () => settle();
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [state, settle]);

  const handleProps = useCallback((index: number) => ({
    onPointerDown: (e: React.PointerEvent) => {
      const li = (e.currentTarget as HTMLElement).closest("li");
      if (!li) return;
      const rect = li.getBoundingClientRect();
      e.preventDefault();
      // Capture on the handle so we keep getting events even if the
      // pointer wanders off the row (common with fast drags).
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      setState({
        fromIndex: index,
        pointerY: e.clientY,
        rowHeight: rect.height || 40,
      });
      setDy(0);
    },
    style: { cursor: "grab", touchAction: "none" } as React.CSSProperties,
  }), []);

  const rowStyle = useCallback((index: number): React.CSSProperties => {
    const s = state;
    if (!s) return {};
    const offset = dy;
    if (index === s.fromIndex) {
      return {
        transform: `translateY(${offset}px)`,
        zIndex: 5,
        opacity: 0.85,
        transition: "none",
      };
    }
    // Other rows shift by one row height when the dragged row crosses
    // their slot. Crude but matches what users expect.
    const shift = Math.round(offset / s.rowHeight);
    const from = s.fromIndex;
    const to = Math.max(0, Math.min(itemCount - 1, from + shift));
    if (from < to && index > from && index <= to) {
      return { transform: `translateY(-${s.rowHeight}px)`,
               transition: "transform 100ms ease" };
    }
    if (from > to && index < from && index >= to) {
      return { transform: `translateY(${s.rowHeight}px)`,
               transition: "transform 100ms ease" };
    }
    return { transition: "transform 100ms ease" };
  }, [state, dy, itemCount]);

  return { handleProps, rowStyle, dragging: state !== null };
}
