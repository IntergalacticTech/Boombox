import { act } from "@testing-library/react";

/** Pretend the window is `width` × `height` and tell resize listeners. */
export function setViewport(width: number, height = 800): void {
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: width });
  Object.defineProperty(window, "innerHeight", { configurable: true, writable: true, value: height });
  act(() => { window.dispatchEvent(new Event("resize")); });
}
