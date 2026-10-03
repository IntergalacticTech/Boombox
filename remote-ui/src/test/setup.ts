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
const _ctxStub = {
  setTransform: () => {}, clearRect: () => {}, fillRect: () => {},
  set fillStyle(_: string) {}, get fillStyle() { return "#000"; },
};
(HTMLCanvasElement.prototype as unknown as {
  getContext: () => unknown;
}).getContext = () => _ctxStub;

// sessionStorage gets the same treatment (the admin token lives there).
const session = new MemoryStorage();
Object.defineProperty(globalThis, "sessionStorage", {
  value: session, writable: true, configurable: true,
});
Object.defineProperty(window, "sessionStorage", {
  value: session, writable: true, configurable: true,
});

// jsdom's window is 1024 px wide — the desktop side of the 900 px
// breakpoint. Default every test to a phone; use setViewport() to switch.
beforeEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 390 });
  Object.defineProperty(window, "innerHeight", { configurable: true, writable: true, value: 844 });
});
