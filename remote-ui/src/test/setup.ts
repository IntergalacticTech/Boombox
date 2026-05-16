import "@testing-library/react";

// Node 25 ships an experimental `globalThis.localStorage` stub (a plain `{}`)
// that shadows jsdom's real `window.localStorage` Storage object. Replace
// the broken stub with a working in-memory Storage so tests that use
// localStorage hit a real API.
class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  get length(): number { return this.data.size; }
  clear(): void { this.data.clear(); }
  getItem(key: string): string | null {
    return this.data.has(key) ? (this.data.get(key) as string) : null;
  }
  key(index: number): string | null {
    return Array.from(this.data.keys())[index] ?? null;
  }
  removeItem(key: string): void { this.data.delete(key); }
  setItem(key: string, value: string): void {
    this.data.set(key, String(value));
  }
}

// Install on both globalThis (where Node's stub lives) and window (where
// jsdom exposes the Storage instance) so either access path works.
const storage = new MemoryStorage();
Object.defineProperty(globalThis, "localStorage", {
  value: storage,
  writable: true,
  configurable: true,
});
Object.defineProperty(window, "localStorage", {
  value: storage,
  writable: true,
  configurable: true,
});

// jsdom doesn't implement canvas 2D context — Visualizer renders to one
// in production but the test environment just needs `getContext` to
// resolve to a stub so the component doesn't pollute test output with
// "Not implemented" errors. The stub mimics enough of CanvasRenderingContext2D
// for our usage (setTransform, clearRect, fillRect, fillStyle setter).
HTMLCanvasElement.prototype.getContext = (() => {
  const stub = {
    setTransform: () => {}, clearRect: () => {}, fillRect: () => {},
    set fillStyle(_: string) {}, get fillStyle() { return "#000"; },
  };
  return () => stub as unknown as CanvasRenderingContext2D;
})() as typeof HTMLCanvasElement.prototype.getContext;
