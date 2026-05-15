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
