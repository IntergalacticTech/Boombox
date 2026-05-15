# PWA Phone Remote — Phase 2A: PWA Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `remote-ui/` — an installable Progressive Web App that pairs with the boombox, controls playback, and matches the device's live theme — served at `/remote/`, consuming the `boombox-remote` API delivered in Phase 1.

**Architecture:** A new Vite/React/TypeScript project (sibling to `ui/`). A transport-agnostic core: a `Transport` interface with an `HttpTransport` (fetch + WebSocket) and an Android-only `BleTransport` (Web Bluetooth against the existing GATT peripheral) — the UI never knows which is active. A React context store fed by transport state pushes drives the screens; the `theme` field of each state push is applied as CSS custom properties so the PWA restyles live with the device skin. `vite-plugin-pwa` makes it installable with an offline app shell. nginx serves the built bundle at `/remote/` from the release tree, exactly like the kiosk SPA at `/`.

**Tech Stack:** Vite 8, React 19, TypeScript ~6.0 (strict, `verbatimModuleSyntax`), `vite-plugin-pwa`, Vitest + `@testing-library/react` + jsdom, bash installers, nginx.

**Scope note:** This is Phase 2A of the PWA work. It delivers a working, installable, deployable PWA with pairing + Now Playing playback control. Phase 2B (Sources, Video, Playlists, desktop Files panel, Extras screens) is a separate plan written against this foundation. The `boombox-remote` API this consumes was delivered in Phase 1 (`docs/superpowers/plans/2026-05-14-pwa-remote-phase1-backend.md`).

**Spec:** `docs/superpowers/specs/2026-05-14-pwa-remote-design.md`

---

## The boombox-remote API this PWA consumes (from Phase 1 — ground truth)

- Base: `/api/remote/` (nginx-proxied to `127.0.0.1:6685`, `auth_basic off`). LAN port `8090`.
- `GET /api/remote/state` → `{ok: true, data: <RemoteState>}` — bearer-token gated.
- `POST /api/remote/command` → body `{action, value?}` → `{ok: bool, error?}` — bearer-token gated.
- `GET /api/remote/ws?token=<tok>` → WebSocket; pushes `{ok: true, data: <RemoteState>}` on change. Closes `4401` (bad token), `4403` (`remote_disabled`).
- `GET /api/remote/art/{hash}.jpg` → album art (bearer-token gated).
- `POST /api/remote/pair` → body `{pin, label}` → `{ok: true, auth_token, boombox_id, boombox_name}` or `{ok: false, error}` (`bad_pin` / `no_active_pin`). NOT token-gated, but 403 `remote_disabled` when the remote is off.
- Auth: `Authorization: Bearer <token>` header (or `?token=` for the WS). When `remote_enabled` is off, gated routes return `403 {"error": "remote_disabled"}`.
- **`RemoteState`** (the consolidated payload) shape: `{boombox: {id, name, version}, source, playing, track: {title, artist, album, duration_s, position_s} | null, art_hash, art_url, volume, muted, sources_available: string[], sleep_timer_s, recording, mic_on, skin, theme}` where `theme` is `{bg, panel, ink, ink2, accent, accent2, rule, font, mono}` (any subset; may be `{}`).
- **BLE GATT** (for `BleTransport`): service `0000bbbb-0000-1000-8000-00805f9b34fb`; characteristics — `device_info` `0000bbbe-…` (read, JSON `{id,name,version}`), `pair_request` `0000bbb1-…` (write, UTF-8 6-digit PIN), `pair_response` `0000bbb2-…` (notify+read, JSON `{ok, auth_token, …}`), `state` `0000bbb3-…` (notify+read, JSON `{ok, data}`), `command` `0000bbb4-…` (write, JSON `{action, value?}`).
- Command actions Now Playing uses: `play_pause`, `next`, `previous`, `stop`, `shuffle`, `mute`, `volume` (value 0-100).

---

## File Structure

**New project — `remote-ui/`:**
- `remote-ui/package.json` — deps + scripts (`dev`, `build`, `test`, `lint`)
- `remote-ui/tsconfig.json`, `tsconfig.app.json`, `tsconfig.node.json` — mirror `ui/`'s strict config
- `remote-ui/vite.config.ts` — Vite + React + `vite-plugin-pwa` + Vitest config; `base: '/remote/'`
- `remote-ui/index.html` — app shell
- `remote-ui/public/icon-192.png`, `icon-512.png` — PWA icons
- `remote-ui/src/main.tsx` — bootstrap
- `remote-ui/src/index.css` — base styles + the CSS custom properties the theme drives
- `remote-ui/src/test/setup.ts` — Vitest/jsdom setup
- `remote-ui/src/transport/types.ts` — `RemoteState`, `Transport` interface, `CommandResult`, transport events
- `remote-ui/src/transport/HttpTransport.ts` — fetch + WebSocket transport
- `remote-ui/src/transport/BleTransport.ts` — Web Bluetooth transport (Android)
- `remote-ui/src/transport/select.ts` — transport selection (HTTP default; BLE offered when available + HTTP unreachable)
- `remote-ui/src/lib/pairing.ts` — PIN→token redemption + `localStorage` persistence
- `remote-ui/src/state/store.tsx` — React context: holds the live `RemoteState`, exposes `command()`, manages the transport
- `remote-ui/src/state/theme.ts` — apply a `theme` object as CSS custom properties on `:root`
- `remote-ui/src/screens/Pairing.tsx` — discover/enter address, enter PIN, store token
- `remote-ui/src/screens/NowPlaying.tsx` — art, track, transport controls, volume
- `remote-ui/src/components/IconButton.tsx` — themed round button used by transport controls
- `remote-ui/src/App.tsx` — root: token gate → Pairing or NowPlaying; surfaces connection / `remote_disabled` state

**Modified (deploy wiring):**
- `install/config/nginx-boombox-common.conf` — add `location /remote/`
- `install/install.sh` — add the `remote-ui` build step
- `install/apply-release.sh` — add `remote-ui` to the `build` subcommand + `preflight` check
- `docs/SERVICES.md`, `docs/ACCESS.md` — note the PWA is now live at `/remote/`

---

## Task 1: Scaffold the `remote-ui/` Vite project

**Files:**
- Create: `remote-ui/package.json`, `remote-ui/tsconfig.json`, `remote-ui/tsconfig.app.json`, `remote-ui/tsconfig.node.json`, `remote-ui/index.html`, `remote-ui/src/main.tsx`, `remote-ui/src/App.tsx`, `remote-ui/src/index.css`, `remote-ui/.gitignore`

- [ ] **Step 1: Create `remote-ui/package.json`**

```json
{
  "name": "remote-ui",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "test": "vitest run",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.2.5",
    "react-dom": "^19.2.5"
  },
  "devDependencies": {
    "@testing-library/react": "^16.1.0",
    "@types/react": "^19.2.14",
    "@types/react-dom": "^19.2.3",
    "@vitejs/plugin-react": "^6.0.1",
    "jsdom": "^25.0.1",
    "typescript": "~6.0.2",
    "vite": "^8.0.10",
    "vite-plugin-pwa": "^1.0.0",
    "vitest": "^3.0.5"
  }
}
```

- [ ] **Step 2: Create the three tsconfig files**

`remote-ui/tsconfig.json`:

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

`remote-ui/tsconfig.app.json` (mirrors `ui/tsconfig.app.json`, plus Vitest globals + Web Bluetooth types via `@types/web` which ships with TS lib `DOM`):

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "es2023",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "module": "esnext",
    "types": ["vite/client", "vitest/globals"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

`remote-ui/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.node.tsbuildinfo",
    "target": "es2023",
    "lib": ["ES2023"],
    "module": "esnext",
    "types": ["node"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 3: Create `remote-ui/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <meta name="theme-color" content="#07060c" />
    <title>Boombox Remote</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 4: Create `remote-ui/src/index.css`**

The theme is driven at runtime by CSS custom properties (Task 9 sets them from the device's theme payload); these are the fallback defaults.

```css
:root {
  --bg: #07060c;
  --panel: #100d1c;
  --ink: #f3f1ff;
  --ink2: #9892b8;
  --accent: #8b5cf6;
  --accent2: #5be7ff;
  --rule: rgba(255, 255, 255, 0.08);
  --font: system-ui, -apple-system, sans-serif;
  --mono: ui-monospace, monospace;
}

* { box-sizing: border-box; }

html, body, #root {
  margin: 0;
  height: 100%;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font);
}

body {
  -webkit-tap-highlight-color: transparent;
  overscroll-behavior: none;
}
```

- [ ] **Step 5: Create `remote-ui/src/App.tsx` (placeholder — fleshed out in Task 10)**

```tsx
export default function App() {
  return <div>Boombox Remote</div>;
}
```

- [ ] **Step 6: Create `remote-ui/src/main.tsx`**

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 7: Create `remote-ui/.gitignore`**

```
node_modules/
dist/
dev-dist/
*.tsbuildinfo
```

- [ ] **Step 8: Commit (the project won't build until Task 2 adds vite.config.ts — that's expected)**

```bash
git add remote-ui/package.json remote-ui/tsconfig.json remote-ui/tsconfig.app.json remote-ui/tsconfig.node.json remote-ui/index.html remote-ui/src/main.tsx remote-ui/src/App.tsx remote-ui/src/index.css remote-ui/.gitignore
git commit -m "feat(remote-ui): scaffold the PWA project"
```

---

## Task 2: Vite config + PWA manifest + Vitest config + icons

**Files:**
- Create: `remote-ui/vite.config.ts`, `remote-ui/src/test/setup.ts`, `remote-ui/public/icon-192.png`, `remote-ui/public/icon-512.png`

- [ ] **Step 1: Create the two PWA icons**

The icons can be solid-color placeholders for now (a real designed icon is out of scope for Phase 2A). Generate them with Python (PIL is in the repo's venv):

Run from the `remote-ui/` directory:
```bash
mkdir -p public
/Users/jwc/code/Boombox/.venv/bin/python -c "
from PIL import Image
for size in (192, 512):
    img = Image.new('RGB', (size, size), '#8b5cf6')
    img.save(f'public/icon-{size}.png')
"
```
Expected: `public/icon-192.png` and `public/icon-512.png` exist.

- [ ] **Step 2: Create `remote-ui/src/test/setup.ts`**

```ts
import "@testing-library/react";
```

- [ ] **Step 3: Create `remote-ui/vite.config.ts`**

`base: '/remote/'` because nginx serves the bundle at `/remote/`. The PWA manifest is installable; the service worker caches the app shell (`autoUpdate` so a new deploy is picked up). Vitest runs in jsdom.

```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  base: "/remote/",
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Boombox Remote",
        short_name: "Boombox",
        description: "Phone remote for the Boombox",
        start_url: "/remote/",
        scope: "/remote/",
        display: "standalone",
        background_color: "#07060c",
        theme_color: "#07060c",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
      workbox: {
        // Cache the app shell so the PWA launches offline (it then shows a
        // connection state until it reaches the boombox).
        globPatterns: ["**/*.{js,css,html,png,woff2}"],
      },
    }),
  ],
  build: {
    outDir: "dist",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

- [ ] **Step 4: Install dependencies and verify the build + test runner work**

Run from `remote-ui/`:
```bash
npm install
npm run build
npm test
```
Expected: `npm install` succeeds; `npm run build` produces `dist/` with `index.html`, a manifest, and a service worker; `npm test` runs (0 tests, exit 0 — no test files yet).

- [ ] **Step 5: Commit**

```bash
git add remote-ui/vite.config.ts remote-ui/src/test/setup.ts remote-ui/public/icon-192.png remote-ui/public/icon-512.png
git commit -m "feat(remote-ui): vite + PWA manifest + vitest config"
```

---

## Task 3: Transport types + interface

**Files:**
- Create: `remote-ui/src/transport/types.ts`, `remote-ui/src/transport/types.test.ts`

- [ ] **Step 1: Write the failing test**

`remote-ui/src/transport/types.test.ts` — a type-level + runtime sanity test that the `RemoteState` shape and `Transport` contract are usable:

```ts
import { describe, it, expect } from "vitest";
import type { RemoteState, Transport, CommandResult } from "./types";

describe("transport types", () => {
  it("RemoteState accepts a full consolidated payload", () => {
    const s: RemoteState = {
      boombox: { id: "b", name: "Boombox", version: 1 },
      source: "mopidy",
      playing: true,
      track: { title: "T", artist: "A", album: "Al",
               duration_s: 100, position_s: 5 },
      art_hash: "abc",
      art_url: "/api/remote/art/abc.jpg",
      volume: 60,
      muted: false,
      sources_available: ["mopidy", "movies"],
      sleep_timer_s: null,
      recording: false,
      mic_on: false,
      skin: "spectrum",
      theme: { bg: "#000", accent: "#0ff" },
    };
    expect(s.track?.title).toBe("T");
  });

  it("RemoteState accepts a minimal/empty payload", () => {
    const s: RemoteState = {
      boombox: { id: "b", name: "B", version: 1 },
      source: null, playing: false, track: null,
      art_hash: null, art_url: null, volume: null, muted: false,
      sources_available: [], sleep_timer_s: null, recording: false,
      mic_on: false, skin: null, theme: {},
    };
    expect(s.track).toBeNull();
  });

  it("CommandResult models ok and error", () => {
    const ok: CommandResult = { ok: true };
    const bad: CommandResult = { ok: false, error: "remote_disabled" };
    expect(ok.ok).toBe(true);
    expect(bad.error).toBe("remote_disabled");
  });

  it("a Transport implementation satisfies the interface", () => {
    const t: Transport = {
      kind: "http",
      async connect() {},
      disconnect() {},
      onState() { return () => {}; },
      async command() { return { ok: true }; },
    };
    expect(t.kind).toBe("http");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `remote-ui/`): `npm test -- types`
Expected: FAIL — `Cannot find module './types'`

- [ ] **Step 3: Create `remote-ui/src/transport/types.ts`**

```ts
// The consolidated state payload from GET /api/remote/state and the WS push.
// Mirrors StateAggregator.consolidated_state() in services/boombox-remote.py.

export interface Track {
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_s: number;
  position_s: number;
}

export interface ThemeVars {
  bg?: string;
  panel?: string;
  ink?: string;
  ink2?: string;
  accent?: string;
  accent2?: string;
  rule?: string;
  font?: string;
  mono?: string;
}

export interface RemoteState {
  boombox: { id: string; name: string; version: number };
  source: string | null;
  playing: boolean;
  track: Track | null;
  art_hash: string | null;
  art_url: string | null;
  volume: number | null;
  muted: boolean;
  sources_available: string[];
  sleep_timer_s: number | null;
  recording: boolean;
  mic_on: boolean;
  skin: string | null;
  theme: ThemeVars;
}

export interface CommandResult {
  ok: boolean;
  error?: string;
}

// Connection status surfaced to the UI. "disabled" = the boombox reported
// remote_disabled (the touchscreen toggle is off).
export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "disabled"
  | "unauthorized"
  | "error";

// Transport-agnostic contract. Both HttpTransport and BleTransport implement
// it; the UI never branches on `kind`. The library/playlists/video/files
// surface is HTTP-only and lives outside this interface (Phase 2B).
export interface Transport {
  readonly kind: "http" | "ble";
  // Establish the connection and begin state pushes. Rejects on a hard
  // failure (bad token, unreachable); resolves once connected.
  connect(): Promise<void>;
  disconnect(): void;
  // Subscribe to state pushes. Returns an unsubscribe function.
  onState(cb: (state: RemoteState) => void): () => void;
  // Subscribe to connection-status changes. Returns an unsubscribe function.
  onStatus?(cb: (status: ConnectionStatus) => void): () => void;
  // Fire a command. Resolves with the boombox's result.
  command(action: string, value?: unknown): Promise<CommandResult>;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- types`
Expected: PASS — 4 passed

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/transport/types.ts remote-ui/src/transport/types.test.ts
git commit -m "feat(remote-ui): transport types + Transport interface"
```

---

## Task 4: HttpTransport

**Files:**
- Create: `remote-ui/src/transport/HttpTransport.ts`, `remote-ui/src/transport/HttpTransport.test.ts`

- [ ] **Step 1: Write the failing test**

`HttpTransport` takes a base URL + bearer token. `connect()` opens the WS; `command()` POSTs. The test uses a fake `WebSocket` and a stubbed `fetch`.

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { HttpTransport } from "./HttpTransport";
import type { RemoteState } from "./types";

// Minimal fake WebSocket installed on globalThis.
class FakeWS {
  static instances: FakeWS[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  constructor(url: string) {
    this.url = url;
    FakeWS.instances.push(this);
  }
  close() { this.readyState = 3; }
  // test helpers
  _open() { this.readyState = 1; this.onopen?.(); }
  _msg(obj: unknown) { this.onmessage?.({ data: JSON.stringify(obj) }); }
  _close(code: number) { this.readyState = 3; this.onclose?.({ code }); }
}

const sampleState: RemoteState = {
  boombox: { id: "b", name: "B", version: 1 },
  source: "mopidy", playing: true, track: null,
  art_hash: null, art_url: null, volume: 50, muted: false,
  sources_available: [], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: {},
};

beforeEach(() => {
  FakeWS.instances = [];
  vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket);
});

describe("HttpTransport", () => {
  it("connect() opens a WS with the token in the query string", async () => {
    const t = new HttpTransport("http://pi:8090", "tok123");
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    expect(FakeWS.instances[0].url).toContain("/api/remote/ws?token=tok123");
    expect(t.kind).toBe("http");
  });

  it("onState() receives pushed state", async () => {
    const t = new HttpTransport("http://pi:8090", "tok");
    const seen: RemoteState[] = [];
    t.onState((s) => seen.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    FakeWS.instances[0]._msg({ ok: true, data: sampleState });
    expect(seen).toHaveLength(1);
    expect(seen[0].source).toBe("mopidy");
  });

  it("a 4403 close surfaces status 'disabled'", async () => {
    const t = new HttpTransport("http://pi:8090", "tok");
    const statuses: string[] = [];
    t.onStatus((s) => statuses.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    FakeWS.instances[0]._close(4403);
    expect(statuses).toContain("disabled");
  });

  it("a 4401 close surfaces status 'unauthorized'", async () => {
    const t = new HttpTransport("http://pi:8090", "tok");
    const statuses: string[] = [];
    t.onStatus((s) => statuses.push(s));
    const p = t.connect();
    FakeWS.instances[0]._open();
    await p;
    FakeWS.instances[0]._close(4401);
    expect(statuses).toContain("unauthorized");
  });

  it("command() POSTs to /api/remote/command with the bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const t = new HttpTransport("http://pi:8090", "tok");
    const res = await t.command("next");
    expect(res).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://pi:8090/api/remote/command",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer tok" }),
      }),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- HttpTransport`
Expected: FAIL — `Cannot find module './HttpTransport'`

- [ ] **Step 3: Create `remote-ui/src/transport/HttpTransport.ts`**

```ts
import type {
  Transport, RemoteState, CommandResult, ConnectionStatus,
} from "./types";

// WebSocket close codes from services/boombox-remote.py's _ws_handler.
const WS_BAD_TOKEN = 4401;
const WS_REMOTE_DISABLED = 4403;

/** Transport over the boombox-remote HTTP + WebSocket API. The default
 *  transport — works on every phone with LAN access to the boombox. */
export class HttpTransport implements Transport {
  readonly kind = "http" as const;

  private readonly base: string;          // e.g. "http://pi:8090"
  private readonly token: string;
  private ws: WebSocket | null = null;
  private stateCbs = new Set<(s: RemoteState) => void>();
  private statusCbs = new Set<(s: ConnectionStatus) => void>();

  constructor(base: string, token: string) {
    this.base = base.replace(/\/$/, "");
    this.token = token;
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const wsUrl = this.base.replace(/^http/, "ws") +
        `/api/remote/ws?token=${encodeURIComponent(this.token)}`;
      const ws = new WebSocket(wsUrl);
      this.ws = ws;
      ws.onopen = () => {
        this.emitStatus("connected");
        resolve();
      };
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg?.ok && msg.data) {
            for (const cb of this.stateCbs) cb(msg.data as RemoteState);
          }
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = (e) => {
        if (e.code === WS_REMOTE_DISABLED) this.emitStatus("disabled");
        else if (e.code === WS_BAD_TOKEN) this.emitStatus("unauthorized");
        else this.emitStatus("error");
        // If the socket closed before it ever opened, the connect() promise
        // is still pending — reject it so the caller sees the failure.
        reject(new Error(`ws closed: ${e.code}`));
      };
      ws.onerror = () => {
        this.emitStatus("error");
        reject(new Error("ws error"));
      };
    });
  }

  disconnect(): void {
    this.ws?.close();
    this.ws = null;
  }

  onState(cb: (s: RemoteState) => void): () => void {
    this.stateCbs.add(cb);
    return () => this.stateCbs.delete(cb);
  }

  onStatus(cb: (s: ConnectionStatus) => void): () => void {
    this.statusCbs.add(cb);
    return () => this.statusCbs.delete(cb);
  }

  async command(action: string, value?: unknown): Promise<CommandResult> {
    try {
      const r = await fetch(`${this.base}/api/remote/command`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.token}`,
        },
        body: JSON.stringify(
          value === undefined ? { action } : { action, value },
        ),
      });
      if (r.status === 403) return { ok: false, error: "remote_disabled" };
      if (r.status === 401) return { ok: false, error: "unauthorized" };
      return (await r.json()) as CommandResult;
    } catch {
      return { ok: false, error: "unreachable" };
    }
  }

  private emitStatus(s: ConnectionStatus) {
    for (const cb of this.statusCbs) cb(s);
  }
}
```

Note: `reject` after `resolve` is a no-op on an already-settled promise — the `onclose`-rejects line is harmless once `onopen` has resolved, and correctly surfaces a connect-time failure when the socket closes before opening.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- HttpTransport`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/transport/HttpTransport.ts remote-ui/src/transport/HttpTransport.test.ts
git commit -m "feat(remote-ui): HttpTransport — fetch + WebSocket"
```

---

## Task 5: BleTransport (Android Web Bluetooth)

**Files:**
- Create: `remote-ui/src/transport/BleTransport.ts`, `remote-ui/src/transport/BleTransport.test.ts`

The `BleTransport` talks to the existing GATT peripheral. It is constructed with an already-connected pairing (a `BluetoothRemoteGATTServer`) plus the GATT characteristics — discovery/pairing happens in the pairing flow (Task 7). This keeps `BleTransport` itself a thin, testable adapter.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, vi } from "vitest";
import { BleTransport } from "./BleTransport";
import type { RemoteState } from "./types";

const sampleState: RemoteState = {
  boombox: { id: "b", name: "B", version: 1 },
  source: "airplay", playing: false, track: null,
  art_hash: null, art_url: null, volume: null, muted: true,
  sources_available: [], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: {},
};

// A fake GATT characteristic supporting notify + write.
function fakeChar() {
  let listener: ((e: Event) => void) | null = null;
  return {
    writes: [] as string[],
    startNotifications: vi.fn().mockResolvedValue(undefined),
    addEventListener: vi.fn((_t: string, cb: (e: Event) => void) => {
      listener = cb;
    }),
    writeValue: vi.fn(function (this: unknown, buf: BufferSource) {
      // record the decoded JSON the transport wrote
      const text = new TextDecoder().decode(buf as ArrayBuffer);
      (this as { writes: string[] }).writes.push(text);
      return Promise.resolve();
    }),
    // test helper: simulate a notify with the given object
    _notify(obj: unknown) {
      const json = JSON.stringify(obj);
      const buf = new TextEncoder().encode(json);
      const evt = { target: { value: new DataView(buf.buffer) } } as unknown as Event;
      listener?.(evt);
    },
  };
}

describe("BleTransport", () => {
  it("kind is 'ble'", () => {
    const state = fakeChar();
    const command = fakeChar();
    const t = new BleTransport(state as never, command as never);
    expect(t.kind).toBe("ble");
  });

  it("connect() subscribes to the state characteristic and pushes parsed state", async () => {
    const state = fakeChar();
    const command = fakeChar();
    const t = new BleTransport(state as never, command as never);
    const seen: RemoteState[] = [];
    t.onState((s) => seen.push(s));
    await t.connect();
    expect(state.startNotifications).toHaveBeenCalled();
    state._notify({ ok: true, data: sampleState });
    expect(seen).toHaveLength(1);
    expect(seen[0].source).toBe("airplay");
  });

  it("command() writes JSON to the command characteristic", async () => {
    const state = fakeChar();
    const command = fakeChar();
    const t = new BleTransport(state as never, command as never);
    await t.command("volume", 70);
    expect(command.writes).toHaveLength(1);
    expect(JSON.parse(command.writes[0])).toEqual({ action: "volume", value: 70 });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- BleTransport`
Expected: FAIL — `Cannot find module './BleTransport'`

- [ ] **Step 3: Create `remote-ui/src/transport/BleTransport.ts`**

```ts
import type {
  Transport, RemoteState, CommandResult, ConnectionStatus,
} from "./types";

// GATT characteristic UUIDs — see services/ble_peripheral.py.
export const BLE_SERVICE_UUID = "0000bbbb-0000-1000-8000-00805f9b34fb";
export const BLE_STATE_UUID = "0000bbb3-0000-1000-8000-00805f9b34fb";
export const BLE_COMMAND_UUID = "0000bbb4-0000-1000-8000-00805f9b34fb";

/** Minimal structural type for the GATT characteristics this transport uses
 *  — keeps the class testable without the full BluetoothRemoteGATT* types. */
export interface BleChar {
  startNotifications(): Promise<unknown>;
  addEventListener(type: "characteristicvaluechanged",
                   cb: (e: Event) => void): void;
  writeValue(value: BufferSource): Promise<void>;
}

/** Transport over the boombox's BLE GATT peripheral. Android/Chrome only
 *  (Web Bluetooth). Constructed with already-resolved `state` and `command`
 *  characteristics — discovery + pairing happen in the pairing flow. */
export class BleTransport implements Transport {
  readonly kind = "ble" as const;

  private readonly stateChar: BleChar;
  private readonly commandChar: BleChar;
  private stateCbs = new Set<(s: RemoteState) => void>();
  private statusCbs = new Set<(s: ConnectionStatus) => void>();

  constructor(stateChar: BleChar, commandChar: BleChar) {
    this.stateChar = stateChar;
    this.commandChar = commandChar;
  }

  async connect(): Promise<void> {
    this.stateChar.addEventListener("characteristicvaluechanged", (e) => {
      const dv = (e.target as { value?: DataView }).value;
      if (!dv) return;
      try {
        const msg = JSON.parse(new TextDecoder().decode(dv));
        if (msg?.ok && msg.data) {
          for (const cb of this.stateCbs) cb(msg.data as RemoteState);
        }
      } catch {
        /* ignore malformed notify */
      }
    });
    await this.stateChar.startNotifications();
    this.emitStatus("connected");
  }

  disconnect(): void {
    // The GATT server lifecycle is owned by the pairing flow that created
    // this transport; nothing to tear down here beyond dropping callbacks.
    this.stateCbs.clear();
    this.statusCbs.clear();
  }

  onState(cb: (s: RemoteState) => void): () => void {
    this.stateCbs.add(cb);
    return () => this.stateCbs.delete(cb);
  }

  onStatus(cb: (s: ConnectionStatus) => void): () => void {
    this.statusCbs.add(cb);
    return () => this.statusCbs.delete(cb);
  }

  async command(action: string, value?: unknown): Promise<CommandResult> {
    const body = value === undefined ? { action } : { action, value };
    try {
      await this.commandChar.writeValue(
        new TextEncoder().encode(JSON.stringify(body)),
      );
      // BLE command writes are fire-and-forget — the peripheral has no
      // per-command response characteristic. Success = the write resolved.
      return { ok: true };
    } catch {
      return { ok: false, error: "unreachable" };
    }
  }

  private emitStatus(s: ConnectionStatus) {
    for (const cb of this.statusCbs) cb(s);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- BleTransport`
Expected: PASS — 3 passed

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/transport/BleTransport.ts remote-ui/src/transport/BleTransport.test.ts
git commit -m "feat(remote-ui): BleTransport — Web Bluetooth adapter"
```

---

## Task 6: Transport selection

**Files:**
- Create: `remote-ui/src/transport/select.ts`, `remote-ui/src/transport/select.test.ts`

`select.ts` decides which transport to build. HTTP is the default; BLE is only *offered* (a capability flag) when `navigator.bluetooth` exists — i.e. Android/Chrome. The PWA uses this to decide whether to show a "connect over Bluetooth" affordance at all. iOS Safari has no `navigator.bluetooth`, so it never sees BLE.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { bleAvailable, makeHttpTransport } from "./select";
import { HttpTransport } from "./HttpTransport";

afterEach(() => { vi.unstubAllGlobals(); });

describe("transport selection", () => {
  it("bleAvailable() is false when navigator.bluetooth is absent (iOS)", () => {
    vi.stubGlobal("navigator", {});
    expect(bleAvailable()).toBe(false);
  });

  it("bleAvailable() is true when navigator.bluetooth exists (Android)", () => {
    vi.stubGlobal("navigator", { bluetooth: {} });
    expect(bleAvailable()).toBe(true);
  });

  it("makeHttpTransport() builds an HttpTransport from base + token", () => {
    const t = makeHttpTransport("http://pi:8090", "tok");
    expect(t).toBeInstanceOf(HttpTransport);
    expect(t.kind).toBe("http");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- select`
Expected: FAIL — `Cannot find module './select'`

- [ ] **Step 3: Create `remote-ui/src/transport/select.ts`**

```ts
import { HttpTransport } from "./HttpTransport";
import type { Transport } from "./types";

/** True when this browser can do Web Bluetooth at all. False on iOS Safari
 *  (no `navigator.bluetooth`), so the PWA never offers BLE there. */
export function bleAvailable(): boolean {
  return typeof navigator !== "undefined" && "bluetooth" in navigator;
}

/** Build the default (HTTP) transport. BLE transports are built by the
 *  pairing flow once a GATT connection exists — see Task 7 / Phase 2B. */
export function makeHttpTransport(base: string, token: string): Transport {
  return new HttpTransport(base, token);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- select`
Expected: PASS — 3 passed

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/transport/select.ts remote-ui/src/transport/select.test.ts
git commit -m "feat(remote-ui): transport selection — HTTP default, BLE capability flag"
```

---

## Task 7: Pairing — PIN redemption + token persistence

**Files:**
- Create: `remote-ui/src/lib/pairing.ts`, `remote-ui/src/lib/pairing.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  redeemPin, loadPairing, savePairing, clearPairing,
} from "./pairing";

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("pairing", () => {
  it("savePairing / loadPairing round-trips base + token", () => {
    savePairing({ base: "http://pi:8090", token: "tok", name: "Boombox" });
    expect(loadPairing()).toEqual({
      base: "http://pi:8090", token: "tok", name: "Boombox",
    });
  });

  it("loadPairing returns null when nothing is stored", () => {
    expect(loadPairing()).toBeNull();
  });

  it("clearPairing removes the stored pairing", () => {
    savePairing({ base: "http://pi:8090", token: "t", name: "B" });
    clearPairing();
    expect(loadPairing()).toBeNull();
  });

  it("redeemPin POSTs the PIN and returns the token on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true, auth_token: "newtok", boombox_name: "Kitchen",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const res = await redeemPin("http://pi:8090", "123456", "my phone");
    expect(res).toEqual({ ok: true, token: "newtok", name: "Kitchen" });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://pi:8090/api/remote/pair",
      expect.objectContaining({ method: "POST" }),
    );
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toEqual({ pin: "123456", label: "my phone" });
  });

  it("redeemPin surfaces a bad-pin error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 403,
      json: async () => ({ ok: false, error: "bad_pin" }),
    }));
    const res = await redeemPin("http://pi:8090", "000000", "x");
    expect(res).toEqual({ ok: false, error: "bad_pin" });
  });

  it("redeemPin surfaces remote_disabled", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 403,
      json: async () => ({ ok: false, error: "remote_disabled" }),
    }));
    const res = await redeemPin("http://pi:8090", "123456", "x");
    expect(res).toEqual({ ok: false, error: "remote_disabled" });
  });

  it("redeemPin surfaces an unreachable boombox", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    const res = await redeemPin("http://pi:8090", "123456", "x");
    expect(res).toEqual({ ok: false, error: "unreachable" });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- pairing`
Expected: FAIL — `Cannot find module './pairing'`

- [ ] **Step 3: Create `remote-ui/src/lib/pairing.ts`**

```ts
const STORAGE_KEY = "boombox-remote-pairing";

export interface Pairing {
  base: string;   // e.g. "http://pi:8090"
  token: string;  // bearer token from /api/remote/pair
  name: string;   // boombox display name
}

export type RedeemResult =
  | { ok: true; token: string; name: string }
  | { ok: false; error: string };

/** Read the persisted pairing, or null. The token is durable — Phase 1's
 *  boombox-remote keeps it in peers.json across reboots. */
export function loadPairing(): Pairing | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw);
    if (p && typeof p.base === "string" && typeof p.token === "string") {
      return { base: p.base, token: p.token, name: p.name ?? "Boombox" };
    }
  } catch {
    /* fall through */
  }
  return null;
}

export function savePairing(p: Pairing): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
}

export function clearPairing(): void {
  localStorage.removeItem(STORAGE_KEY);
}

/** Redeem a 6-digit PIN for a durable bearer token via POST /api/remote/pair.
 *  `base` is the boombox LAN origin (e.g. "http://192.168.1.5:8090"). */
export async function redeemPin(
  base: string, pin: string, label: string,
): Promise<RedeemResult> {
  const origin = base.replace(/\/$/, "");
  try {
    const r = await fetch(`${origin}/api/remote/pair`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin, label }),
    });
    const body = await r.json().catch(() => ({}));
    if (body?.ok && body.auth_token) {
      return {
        ok: true,
        token: body.auth_token as string,
        name: (body.boombox_name as string) ?? "Boombox",
      };
    }
    return { ok: false, error: (body?.error as string) ?? "pair_failed" };
  } catch {
    return { ok: false, error: "unreachable" };
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- pairing`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/lib/pairing.ts remote-ui/src/lib/pairing.test.ts
git commit -m "feat(remote-ui): pairing — PIN redemption + durable token storage"
```

---

## Task 8: Theme application

**Files:**
- Create: `remote-ui/src/state/theme.ts`, `remote-ui/src/state/theme.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { applyTheme } from "./theme";
import type { ThemeVars } from "../transport/types";

beforeEach(() => {
  document.documentElement.removeAttribute("style");
});

describe("applyTheme", () => {
  it("sets each provided theme value as a CSS custom property on :root", () => {
    const theme: ThemeVars = { bg: "#000", accent: "#0ff", font: "Inter" };
    applyTheme(theme);
    const root = document.documentElement;
    expect(root.style.getPropertyValue("--bg")).toBe("#000");
    expect(root.style.getPropertyValue("--accent")).toBe("#0ff");
    expect(root.style.getPropertyValue("--font")).toBe("Inter");
  });

  it("ignores keys not present in the theme object", () => {
    applyTheme({ bg: "#111" });
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("");
  });

  it("an empty theme object is a no-op", () => {
    applyTheme({});
    expect(document.documentElement.getAttribute("style")).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- theme`
Expected: FAIL — `Cannot find module './theme'`

- [ ] **Step 3: Create `remote-ui/src/state/theme.ts`**

```ts
import type { ThemeVars } from "../transport/types";

// theme key → CSS custom property name. The boombox sends the same nine
// keys the kiosk skins use (see services/boombox-state.py's theme payload).
const VAR_MAP: Record<keyof ThemeVars, string> = {
  bg: "--bg",
  panel: "--panel",
  ink: "--ink",
  ink2: "--ink2",
  accent: "--accent",
  accent2: "--accent2",
  rule: "--rule",
  font: "--font",
  mono: "--mono",
};

/** Apply a theme payload as CSS custom properties on :root, so the whole
 *  PWA restyles live when the device skin changes. Missing keys are left
 *  untouched (the index.css fallbacks hold). */
export function applyTheme(theme: ThemeVars): void {
  const root = document.documentElement;
  for (const key of Object.keys(VAR_MAP) as (keyof ThemeVars)[]) {
    const value = theme[key];
    if (typeof value === "string" && value) {
      root.style.setProperty(VAR_MAP[key], value);
    }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- theme`
Expected: PASS — 3 passed

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/state/theme.ts remote-ui/src/state/theme.test.ts
git commit -m "feat(remote-ui): live theme — apply device skin as CSS vars"
```

---

## Task 9: State store (React context)

**Files:**
- Create: `remote-ui/src/state/store.tsx`, `remote-ui/src/state/store.test.tsx`

The store owns a transport, subscribes to its state pushes, applies the theme on every push, exposes the latest `RemoteState` + connection status + a `command()` passthrough to React via context.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { TransportProvider, useRemote } from "./store";
import type {
  Transport, RemoteState, ConnectionStatus,
} from "../transport/types";

function makeFakeTransport() {
  let stateCb: ((s: RemoteState) => void) | null = null;
  let statusCb: ((s: ConnectionStatus) => void) | null = null;
  const t: Transport = {
    kind: "http",
    connect: vi.fn().mockResolvedValue(undefined),
    disconnect: vi.fn(),
    onState: (cb) => { stateCb = cb; return () => {}; },
    onStatus: (cb) => { statusCb = cb; return () => {}; },
    command: vi.fn().mockResolvedValue({ ok: true }),
  };
  return {
    transport: t,
    pushState: (s: RemoteState) => stateCb?.(s),
    pushStatus: (s: ConnectionStatus) => statusCb?.(s),
  };
}

const sample: RemoteState = {
  boombox: { id: "b", name: "B", version: 1 },
  source: "mopidy", playing: true,
  track: { title: "Hey", artist: "X", album: "Y",
           duration_s: 10, position_s: 1 },
  art_hash: null, art_url: null, volume: 42, muted: false,
  sources_available: [], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: { bg: "#abc" },
};

function Probe() {
  const { state, status } = useRemote();
  return (
    <div>
      <span data-testid="title">{state?.track?.title ?? "—"}</span>
      <span data-testid="status">{status}</span>
    </div>
  );
}

describe("TransportProvider / useRemote", () => {
  it("connects the transport and exposes pushed state", async () => {
    const { transport, pushState } = makeFakeTransport();
    render(
      <TransportProvider transport={transport}>
        <Probe />
      </TransportProvider>,
    );
    expect(transport.connect).toHaveBeenCalled();
    expect(screen.getByTestId("title").textContent).toBe("—");
    await act(async () => { pushState(sample); });
    expect(screen.getByTestId("title").textContent).toBe("Hey");
  });

  it("applies the theme from each state push", async () => {
    const { transport, pushState } = makeFakeTransport();
    render(
      <TransportProvider transport={transport}>
        <Probe />
      </TransportProvider>,
    );
    await act(async () => { pushState(sample); });
    expect(document.documentElement.style.getPropertyValue("--bg"))
      .toBe("#abc");
  });

  it("exposes connection status changes", async () => {
    const { transport, pushStatus } = makeFakeTransport();
    render(
      <TransportProvider transport={transport}>
        <Probe />
      </TransportProvider>,
    );
    await act(async () => { pushStatus("disabled"); });
    expect(screen.getByTestId("status").textContent).toBe("disabled");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- store`
Expected: FAIL — `Cannot find module './store'`

- [ ] **Step 3: Create `remote-ui/src/state/store.tsx`**

```tsx
import {
  createContext, useContext, useEffect, useRef, useState,
} from "react";
import type { ReactNode } from "react";
import type {
  Transport, RemoteState, ConnectionStatus, CommandResult,
} from "../transport/types";
import { applyTheme } from "./theme";

interface RemoteContextValue {
  state: RemoteState | null;
  status: ConnectionStatus;
  command(action: string, value?: unknown): Promise<CommandResult>;
}

const RemoteContext = createContext<RemoteContextValue | null>(null);

/** Owns the transport: connects it, subscribes to state + status pushes,
 *  applies the device theme on every state push, and exposes everything to
 *  the tree via context. */
export function TransportProvider(
  { transport, children }: { transport: Transport; children: ReactNode },
) {
  const [state, setState] = useState<RemoteState | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const transportRef = useRef(transport);
  transportRef.current = transport;

  useEffect(() => {
    const t = transport;
    const offState = t.onState((s) => {
      setState(s);
      applyTheme(s.theme);
    });
    const offStatus = t.onStatus?.((s) => setStatus(s));
    t.connect()
      .then(() => setStatus("connected"))
      .catch(() => setStatus("error"));
    return () => {
      offState();
      offStatus?.();
      t.disconnect();
    };
  }, [transport]);

  const value: RemoteContextValue = {
    state,
    status,
    command: (action, v) => transportRef.current.command(action, v),
  };
  return (
    <RemoteContext.Provider value={value}>{children}</RemoteContext.Provider>
  );
}

/** Access the live remote state, connection status, and command sender. */
export function useRemote(): RemoteContextValue {
  const ctx = useContext(RemoteContext);
  if (!ctx) {
    throw new Error("useRemote must be used within a TransportProvider");
  }
  return ctx;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- store`
Expected: PASS — 3 passed

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/state/store.tsx remote-ui/src/state/store.test.tsx
git commit -m "feat(remote-ui): transport-backed state store + live theming"
```

---

## Task 10: Pairing screen

**Files:**
- Create: `remote-ui/src/screens/Pairing.tsx`, `remote-ui/src/screens/Pairing.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Pairing } from "./Pairing";

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("Pairing screen", () => {
  it("redeems the PIN and calls onPaired with the new pairing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true, auth_token: "tok99", boombox_name: "Garage",
      }),
    }));
    const onPaired = vi.fn();
    render(<Pairing onPaired={onPaired} />);

    fireEvent.change(screen.getByLabelText(/boombox address/i),
                     { target: { value: "192.168.1.9" } });
    fireEvent.change(screen.getByLabelText(/pin/i),
                     { target: { value: "654321" } });
    fireEvent.click(screen.getByRole("button", { name: /pair/i }));

    await waitFor(() => expect(onPaired).toHaveBeenCalled());
    expect(onPaired).toHaveBeenCalledWith({
      base: "http://192.168.1.9:8090", token: "tok99", name: "Garage",
    });
  });

  it("shows an error message when the PIN is rejected", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 403,
      json: async () => ({ ok: false, error: "bad_pin" }),
    }));
    render(<Pairing onPaired={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/boombox address/i),
                     { target: { value: "pi" } });
    fireEvent.change(screen.getByLabelText(/pin/i),
                     { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: /pair/i }));
    await waitFor(() =>
      expect(screen.getByText(/incorrect pin/i)).toBeTruthy());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- Pairing`
Expected: FAIL — `Cannot find module './Pairing'`

- [ ] **Step 3: Create `remote-ui/src/screens/Pairing.tsx`**

```tsx
import { useState } from "react";
import { redeemPin, savePairing } from "../lib/pairing";
import type { Pairing as PairingData } from "../lib/pairing";

const ERRORS: Record<string, string> = {
  bad_pin: "Incorrect PIN — check the boombox screen and try again.",
  no_active_pin: "That PIN expired. Generate a new one on the boombox.",
  remote_disabled: "Remote access is off — turn it on in the boombox's Settings.",
  unreachable: "Couldn't reach that boombox. Check the address and your WiFi.",
};

/** Address + PIN entry. Resolves a host into the LAN origin
 *  `http://<host>:8090`, redeems the PIN, persists the pairing, and hands
 *  it up via onPaired. */
export function Pairing({ onPaired }: { onPaired: (p: PairingData) => void }) {
  const [host, setHost] = useState("");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const normalizeBase = (h: string): string => {
    const trimmed = h.trim().replace(/\/$/, "");
    if (/^https?:\/\//.test(trimmed)) return trimmed;
    return `http://${trimmed}:8090`;
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const base = normalizeBase(host);
    const res = await redeemPin(base, pin.trim(), "phone");
    setBusy(false);
    if (res.ok) {
      const pairing: PairingData = { base, token: res.token, name: res.name };
      savePairing(pairing);
      onPaired(pairing);
    } else {
      setError(ERRORS[res.error] ?? "Pairing failed. Try again.");
    }
  };

  return (
    <form onSubmit={submit} style={{
      display: "flex", flexDirection: "column", gap: 16,
      padding: 24, maxWidth: 420, margin: "0 auto",
    }}>
      <h1 style={{ fontSize: 24, margin: 0 }}>Pair with your Boombox</h1>
      <p style={{ color: "var(--ink2)", margin: 0, fontSize: 14 }}>
        Open Settings → Phone remote on the boombox to turn it on and get a PIN.
      </p>

      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={{ fontSize: 13, color: "var(--ink2)" }}>
          Boombox address
        </span>
        <input
          value={host}
          onChange={(e) => setHost(e.target.value)}
          placeholder="boombox.local — or its IP"
          autoCapitalize="off" autoCorrect="off" spellCheck={false}
          style={inputStyle}
        />
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={{ fontSize: 13, color: "var(--ink2)" }}>PIN</span>
        <input
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))}
          inputMode="numeric" placeholder="6 digits"
          style={{ ...inputStyle, letterSpacing: "0.3em" }}
        />
      </label>

      {error && (
        <div role="alert" style={{ color: "#ff7878", fontSize: 14 }}>
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={busy || pin.length !== 6 || host.trim() === ""}
        style={{
          padding: "14px 16px", borderRadius: 12, border: 0,
          background: "var(--accent)", color: "var(--bg)",
          fontSize: 16, fontWeight: 700,
          opacity: busy || pin.length !== 6 || !host.trim() ? 0.5 : 1,
        }}
      >
        {busy ? "Pairing…" : "Pair"}
      </button>
    </form>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "12px 14px", borderRadius: 10,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", fontSize: 18,
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- Pairing`
Expected: PASS — 2 passed

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/screens/Pairing.tsx remote-ui/src/screens/Pairing.test.tsx
git commit -m "feat(remote-ui): pairing screen"
```

---

## Task 11: IconButton component

**Files:**
- Create: `remote-ui/src/components/IconButton.tsx`, `remote-ui/src/components/IconButton.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { IconButton } from "./IconButton";

describe("IconButton", () => {
  it("renders its label and fires onClick", () => {
    const onClick = vi.fn();
    render(<IconButton label="Next" onClick={onClick}>››</IconButton>);
    const btn = screen.getByRole("button", { name: "Next" });
    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("does not fire onClick when disabled", () => {
    const onClick = vi.fn();
    render(
      <IconButton label="Next" onClick={onClick} disabled>››</IconButton>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("applies the primary variant styling flag via data attribute", () => {
    render(
      <IconButton label="Play" onClick={() => {}} primary>▶</IconButton>,
    );
    expect(screen.getByRole("button", { name: "Play" }))
      .toHaveProperty("dataset.primary", "true");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- IconButton`
Expected: FAIL — `Cannot find module './IconButton'`

- [ ] **Step 3: Create `remote-ui/src/components/IconButton.tsx`**

```tsx
import type { ReactNode } from "react";

/** A round, themed touch button. `primary` makes it larger + accent-filled
 *  (used for play/pause); the rest are outline buttons. */
export function IconButton(
  { label, onClick, children, disabled = false, primary = false }: {
    label: string;
    onClick: () => void;
    children: ReactNode;
    disabled?: boolean;
    primary?: boolean;
  },
) {
  const size = primary ? 72 : 56;
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      data-primary={primary}
      style={{
        width: size, height: size, borderRadius: "50%",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        fontSize: primary ? 28 : 22, lineHeight: 1,
        border: primary ? 0 : "1px solid var(--rule)",
        background: primary ? "var(--accent)" : "var(--panel)",
        color: primary ? "var(--bg)" : "var(--ink)",
        opacity: disabled ? 0.4 : 1,
        cursor: disabled ? "default" : "pointer",
        flexShrink: 0,
      }}
    >
      {children}
    </button>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- IconButton`
Expected: PASS — 3 passed

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/components/IconButton.tsx remote-ui/src/components/IconButton.test.tsx
git commit -m "feat(remote-ui): IconButton component"
```

---

## Task 12: Now Playing screen

**Files:**
- Create: `remote-ui/src/screens/NowPlaying.tsx`, `remote-ui/src/screens/NowPlaying.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NowPlaying } from "./NowPlaying";
import { RemoteContextHarness } from "../state/store";
import type { RemoteState } from "../transport/types";

const playing: RemoteState = {
  boombox: { id: "b", name: "Kitchen", version: 1 },
  source: "mopidy", playing: true,
  track: { title: "Hey Jude", artist: "The Beatles", album: "1967-1970",
           duration_s: 431, position_s: 60 },
  art_hash: null, art_url: null, volume: 65, muted: false,
  sources_available: ["mopidy"], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: {},
};

describe("NowPlaying", () => {
  it("renders the current track", () => {
    render(
      <RemoteContextHarness state={playing} command={vi.fn()}>
        <NowPlaying />
      </RemoteContextHarness>,
    );
    expect(screen.getByText("Hey Jude")).toBeTruthy();
    expect(screen.getByText(/The Beatles/)).toBeTruthy();
  });

  it("the play/pause button fires play_pause", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <RemoteContextHarness state={playing} command={command}>
        <NowPlaying />
      </RemoteContextHarness>,
    );
    fireEvent.click(screen.getByRole("button", { name: /pause/i }));
    expect(command).toHaveBeenCalledWith("play_pause");
  });

  it("next / previous fire their commands", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <RemoteContextHarness state={playing} command={command}>
        <NowPlaying />
      </RemoteContextHarness>,
    );
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    fireEvent.click(screen.getByRole("button", { name: /previous/i }));
    expect(command).toHaveBeenCalledWith("next");
    expect(command).toHaveBeenCalledWith("previous");
  });

  it("the volume slider fires a volume command with the new value", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <RemoteContextHarness state={playing} command={command}>
        <NowPlaying />
      </RemoteContextHarness>,
    );
    fireEvent.change(screen.getByLabelText(/volume/i),
                     { target: { value: "80" } });
    expect(command).toHaveBeenCalledWith("volume", 80);
  });

  it("shows a placeholder when nothing is playing", () => {
    const idle: RemoteState = { ...playing, track: null, playing: false };
    render(
      <RemoteContextHarness state={idle} command={vi.fn()}>
        <NowPlaying />
      </RemoteContextHarness>,
    );
    expect(screen.getByText(/nothing playing/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Add the `RemoteContextHarness` test helper to `store.tsx`**

The test renders `NowPlaying` with a controlled context. Add this exported helper to `remote-ui/src/state/store.tsx` (it shares the same `RemoteContext`, so `useRemote()` works inside it):

```tsx
/** Test/Storybook helper: provide a fixed RemoteState + command spy without
 *  a real transport. Not used in production. */
export function RemoteContextHarness(
  { state, command, status = "connected", children }: {
    state: RemoteState | null;
    command: (action: string, value?: unknown) => Promise<CommandResult>;
    status?: ConnectionStatus;
    children: ReactNode;
  },
) {
  return (
    <RemoteContext.Provider value={{ state, status, command }}>
      {children}
    </RemoteContext.Provider>
  );
}
```

(Add `CommandResult` to the existing `import type { … } from "../transport/types"` line in `store.tsx` if not already imported.)

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- NowPlaying`
Expected: FAIL — `Cannot find module './NowPlaying'`

- [ ] **Step 4: Create `remote-ui/src/screens/NowPlaying.tsx`**

```tsx
import { useRemote } from "../state/store";
import { IconButton } from "../components/IconButton";

function mmss(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** The core remote: album art, current track, transport controls, volume. */
export function NowPlaying() {
  const { state, command } = useRemote();
  const track = state?.track ?? null;
  const playing = state?.playing ?? false;
  const volume = state?.volume ?? 0;

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 24,
      padding: 24, maxWidth: 520, margin: "0 auto", alignItems: "center",
    }}>
      <div style={{
        width: "min(70vw, 320px)", aspectRatio: "1",
        borderRadius: 16, background: "var(--panel)",
        border: "1px solid var(--rule)",
        display: "grid", placeItems: "center", overflow: "hidden",
      }}>
        {state?.art_url
          ? <img src={state.art_url} alt=""
                 style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          : <span style={{ color: "var(--ink2)", fontSize: 13 }}>no art</span>}
      </div>

      <div style={{ textAlign: "center", minHeight: 64 }}>
        {track
          ? <>
              <div style={{ fontSize: 22, fontWeight: 800 }}>
                {track.title ?? "Untitled"}
              </div>
              <div style={{ color: "var(--ink2)", marginTop: 4 }}>
                {[track.artist, track.album].filter(Boolean).join(" · ") || " "}
              </div>
              <div style={{
                color: "var(--ink2)", fontFamily: "var(--mono)",
                fontSize: 13, marginTop: 6,
              }}>
                {mmss(track.position_s)} / {mmss(track.duration_s)}
              </div>
            </>
          : <div style={{ color: "var(--ink2)", fontSize: 16 }}>
              Nothing playing
            </div>}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <IconButton label="Previous" onClick={() => command("previous")}>
          ‹‹
        </IconButton>
        <IconButton label={playing ? "Pause" : "Play"} primary
                    onClick={() => command("play_pause")}>
          {playing ? "❚❚" : "▶"}
        </IconButton>
        <IconButton label="Next" onClick={() => command("next")}>
          ››
        </IconButton>
        <IconButton label="Stop" onClick={() => command("stop")}>
          ■
        </IconButton>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12,
                    width: "100%" }}>
        <IconButton label={state?.muted ? "Unmute" : "Mute"}
                    onClick={() => command("mute")}>
          {state?.muted ? "🔇" : "🔊"}
        </IconButton>
        <input
          aria-label="Volume"
          type="range" min={0} max={100} value={volume}
          onChange={(e) => command("volume", Number(e.target.value))}
          style={{ flex: 1, accentColor: "var(--accent)" }}
        />
        <span style={{ fontFamily: "var(--mono)", fontSize: 13,
                       color: "var(--ink2)", width: 38, textAlign: "right" }}>
          {volume}
        </span>
      </div>

      <IconButton label="Shuffle" onClick={() => command("shuffle")}>
        🔀
      </IconButton>
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- NowPlaying`
Expected: PASS — 5 passed

- [ ] **Step 6: Commit**

```bash
git add remote-ui/src/screens/NowPlaying.tsx remote-ui/src/screens/NowPlaying.test.tsx remote-ui/src/state/store.tsx
git commit -m "feat(remote-ui): Now Playing screen"
```

---

## Task 13: App shell — token gate, connection state, routing

**Files:**
- Modify: `remote-ui/src/App.tsx` (replace the Task 1 placeholder)
- Create: `remote-ui/src/App.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("shows the pairing screen when there is no stored pairing", () => {
    render(<App />);
    expect(screen.getByText(/pair with your boombox/i)).toBeTruthy();
  });

  it("shows the remote (not pairing) when a pairing is stored", () => {
    localStorage.setItem("boombox-remote-pairing", JSON.stringify({
      base: "http://pi:8090", token: "t", name: "Kitchen",
    }));
    // Stub WebSocket so TransportProvider's connect() doesn't throw.
    class StubWS {
      onopen: (() => void) | null = null;
      onmessage: unknown = null;
      onclose: unknown = null;
      onerror: unknown = null;
      constructor() { setTimeout(() => this.onopen?.(), 0); }
      close() {}
    }
    vi.stubGlobal("WebSocket", StubWS as unknown as typeof WebSocket);
    render(<App />);
    // The pairing screen's heading must NOT be present.
    expect(screen.queryByText(/pair with your boombox/i)).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- App`
Expected: FAIL — the placeholder `App` renders neither screen

- [ ] **Step 3: Replace `remote-ui/src/App.tsx`**

```tsx
import { useState } from "react";
import { loadPairing, clearPairing } from "./lib/pairing";
import type { Pairing } from "./lib/pairing";
import { makeHttpTransport } from "./transport/select";
import { TransportProvider, useRemote } from "./state/store";
import { Pairing as PairingScreen } from "./screens/Pairing";
import { NowPlaying } from "./screens/NowPlaying";

/** Inside the provider: routes on connection status. */
function Remote({ onUnpair }: { onUnpair: () => void }) {
  const { status } = useRemote();

  if (status === "disabled") {
    return (
      <Centered>
        <h2>Remote access is off</h2>
        <p style={{ color: "var(--ink2)" }}>
          Turn it on in the boombox's Settings → Phone remote, then this will
          reconnect automatically.
        </p>
      </Centered>
    );
  }
  if (status === "unauthorized") {
    return (
      <Centered>
        <h2>This phone is no longer paired</h2>
        <p style={{ color: "var(--ink2)" }}>
          It was unpaired from the boombox. Pair again to reconnect.
        </p>
        <button onClick={onUnpair} style={linkBtn}>Pair again</button>
      </Centered>
    );
  }
  if (status === "error" || status === "connecting") {
    return (
      <Centered>
        <p style={{ color: "var(--ink2)" }}>
          {status === "connecting" ? "Connecting…" : "Can't reach the boombox."}
        </p>
      </Centered>
    );
  }
  return <NowPlaying />;
}

export default function App() {
  const [pairing, setPairing] = useState<Pairing | null>(() => loadPairing());

  if (!pairing) {
    return <PairingScreen onPaired={setPairing} />;
  }

  const unpair = () => {
    clearPairing();
    setPairing(null);
  };

  // `key` forces a fresh TransportProvider (new transport) when the pairing
  // changes — e.g. after re-pairing.
  return (
    <TransportProvider
      key={pairing.token}
      transport={makeHttpTransport(pairing.base, pairing.token)}
    >
      <Remote onUnpair={unpair} />
    </TransportProvider>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      minHeight: "100%", display: "grid", placeItems: "center",
      padding: 24, textAlign: "center",
    }}>
      <div style={{ maxWidth: 420 }}>{children}</div>
    </div>
  );
}

const linkBtn: React.CSSProperties = {
  marginTop: 12, padding: "10px 18px", borderRadius: 10,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", fontSize: 15, cursor: "pointer",
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- App`
Expected: PASS — 2 passed

- [ ] **Step 5: Run the full test suite + build**

Run: `npm test` then `npm run build`
Expected: all tests pass (across all `*.test.ts(x)` files); `npm run build` exits 0 with the bundle + PWA manifest + service worker in `dist/`.

- [ ] **Step 6: Commit**

```bash
git add remote-ui/src/App.tsx remote-ui/src/App.test.tsx
git commit -m "feat(remote-ui): app shell — token gate + connection-state routing"
```

---

## Task 14: Deploy wiring — nginx + install + apply-release

**Files:**
- Modify: `install/config/nginx-boombox-common.conf`, `install/install.sh`, `install/apply-release.sh`

This follows the established pattern: the kiosk SPA (`ui/`) is built in place in the release tree and nginx serves it from `current/ui/dist`. `remote-ui/` mirrors that — built in place, served at `/remote/` from `current/remote-ui/dist`.

- [ ] **Step 1: Add the `/remote/` location to nginx**

In `install/config/nginx-boombox-common.conf`, add this block (place it just before the `location /api/remote/` block so the static route is grouped with the API it consumes):

```nginx
# Phone-remote PWA — static SPA served from the release tree, like the
# kiosk SPA at /. auth_basic off so phones go straight to PIN pairing
# (the API it calls, /api/remote/, is bearer-token gated).
location /remote/ {
    auth_basic off;
    alias /opt/boombox/current/remote-ui/dist/;
    try_files $uri $uri/ /opt/boombox/current/remote-ui/dist/index.html;
}
```

- [ ] **Step 2: Add the `remote-ui` build to `install.sh`**

In `install/install.sh`, find the `# 7. Build UI in place` section (the `(cd "$ACTIVE_REPO/ui"; npm install …; npm run build)` block). Immediately after it — after the `chmod -R a+rX "$ACTIVE_REPO/ui/dist"` / `chmod o+x …` lines for `ui` — add the parallel block for `remote-ui`:

```bash
log "building remote-ui (PWA) in $ACTIVE_REPO/remote-ui"
(
  cd "$ACTIVE_REPO/remote-ui"
  npm install --no-audit --no-fund
  npm run build
)
chmod -R a+rX "$ACTIVE_REPO/remote-ui/dist"
chmod o+x "$ACTIVE_REPO/remote-ui"
```

- [ ] **Step 3: Add the `remote-ui` build to `apply-release.sh`**

In `install/apply-release.sh`, find the `build)` subcommand's `( cd "$RELEASES/$ref/ui"; npm install …; npm run build )` block. After it — after the `chmod -R a+rX "$RELEASES/$ref/ui/dist"` / `chmod o+x …` lines — add:

```bash
    (
      cd "$RELEASES/$ref/remote-ui"
      npm install --no-audit --no-fund
      npm run build
    )
    chmod -R a+rX "$RELEASES/$ref/remote-ui/dist"
    chmod o+x "$RELEASES/$ref/remote-ui"
```

In the same file, find the `preflight)` subcommand and add a check next to the existing `[[ -f "$RELEASES/$ref/ui/dist/index.html" ]]` line:

```bash
    [[ -f "$RELEASES/$ref/remote-ui/dist/index.html" ]] || fail "remote-ui/dist/index.html missing"
```

- [ ] **Step 4: Verify the nginx config is still syntactically valid**

If `nginx` is available on the dev box: `nginx -t -c <(...)` as in Phase 1 — otherwise skip; `apply-release.sh preflight` runs `sudo /usr/sbin/nginx -t` on the Pi. At minimum, visually confirm the new `location /remote/` block is well-formed (matched braces, semicolons).

Run a sanity grep:
```bash
grep -n "location /remote/" install/config/nginx-boombox-common.conf
grep -n "remote-ui" install/install.sh install/apply-release.sh
```
Expected: the `/remote/` location is present once; `remote-ui` appears in both install scripts.

- [ ] **Step 5: Commit**

```bash
git add install/config/nginx-boombox-common.conf install/install.sh install/apply-release.sh
git commit -m "feat(deploy): serve the remote-ui PWA at /remote/"
```

---

## Task 15: Docs — note the PWA is live at `/remote/`

**Files:**
- Modify: `docs/ACCESS.md`, `docs/SERVICES.md`

Phase 1's docs say the phone web-app UI is "Phase 2 — not built yet" and the QR points at a not-yet-served path. Phase 2A makes `/remote/` real — update those notes.

- [ ] **Step 1: Update `docs/ACCESS.md`**

Read `docs/ACCESS.md`. Find the "What's real today vs. Phase 2" callout (near the top of the "Remote access" section) and the references to the phone web app being "forthcoming"/"Phase 2 — not built." Update them: the PWA now exists — it's served at `http://<pi-ip>:8090/remote/`, installable from the phone's browser ("Add to Home Screen"), and is the thing the touchscreen's QR overlay points at. Keep it accurate to Phase 2A's actual scope: pairing + Now Playing playback control work; the Sources/Video/Playlists/Files/Extras screens are the Phase 2B follow-up. Don't overclaim.

- [ ] **Step 2: Update `docs/SERVICES.md`**

Read `docs/SERVICES.md`. In the `boombox-remote` section, the note that the `/remote/` PWA is "Phase 2 — not built yet" should change to: the PWA is served by nginx at `/remote/` from `current/remote-ui/dist` (built in place like the kiosk SPA). Keep the API documentation itself unchanged — only the "what consumes it" framing changes.

- [ ] **Step 3: Verify**

```bash
grep -rn "not built\|forthcoming\|Phase 2 — not" docs/ACCESS.md docs/SERVICES.md
```
Expected: no matches that still claim the PWA doesn't exist (a forward-reference to Phase 2B's *additional screens* is fine; "the PWA doesn't exist yet" is not).

- [ ] **Step 4: Commit**

```bash
git add docs/ACCESS.md docs/SERVICES.md
git commit -m "docs: the remote-ui PWA is live at /remote/"
```

---

## Final verification

- [ ] **Run the full `remote-ui` test suite**

Run (from `remote-ui/`): `npm test`
Expected: all green — every `*.test.ts(x)` file across tasks 3-13.

- [ ] **Build the PWA**

Run (from `remote-ui/`): `npm run build`
Expected: exit 0; `dist/` contains `index.html`, hashed JS/CSS, `manifest.webmanifest`, and a service worker (`sw.js` or `registerSW.js`).

- [ ] **Confirm the kiosk SPA still builds** (deploy wiring touched shared install scripts, not `ui/` — but confirm nothing regressed)

Run (from `ui/`): `npm run build`
Expected: exit 0, no TypeScript errors.

- [ ] **Confirm the Phase 1 backend suite still passes** (Phase 2A didn't touch `services/` — sanity check)

Run: `/Users/jwc/code/Boombox/.venv/bin/python -m pytest services/tests/ -q`
Expected: 164 passed.

---

## Self-Review (completed during planning)

**Spec coverage (Phase 2A scope):**
- New `remote-ui/` Vite/React/TS project → Tasks 1-2
- PWA manifest + service worker (installable, offline shell) → Task 2 (`vite-plugin-pwa`)
- Transport interface + `HttpTransport` + `BleTransport` + selection → Tasks 3-6
- Pairing (PIN → durable token, `localStorage`) → Tasks 7, 10
- State store fed by transport pushes → Task 9
- Live theming (device skin → CSS vars) → Tasks 8, 9
- Now Playing screen (art, transport, volume) → Tasks 11-12
- App shell — token gate, connection/`remote_disabled` states → Task 13
- nginx `/remote/` location + `remote-ui` build step in install.sh/apply-release.sh → Task 14
- Docs updated to reflect the PWA exists → Task 15
- *Deferred to Phase 2B (separate plan):* Sources, Video, Playlists, desktop Files panel, Extras screens; the HTTP-only `api.ts` wrappers (library/playlists/queue/video/files) those screens need; the full BLE *discovery + pairing* flow (Task 5's `BleTransport` is the adapter; wiring Web Bluetooth device selection + GATT pairing into the pairing screen is 2B, since 2A's pairing screen covers the universal HTTP path).

**Placeholder scan:** No TBD/TODO. Every code step shows complete code. Task 1 Step 5 is an intentional placeholder `App.tsx` that Task 13 replaces — called out explicitly in both tasks.

**Type consistency:** `RemoteState`/`Transport`/`CommandResult`/`ConnectionStatus` defined in Task 3 (`transport/types.ts`) and consumed unchanged in Tasks 4-13. `Pairing` type defined in Task 7 (`lib/pairing.ts`), consumed in Tasks 10 + 13. `RemoteContextHarness` added to `store.tsx` in Task 12 Step 2, used by the NowPlaying test. `makeHttpTransport`/`bleAvailable` from Task 6 used in Task 13. `applyTheme` from Task 8 used in Task 9. `IconButton` from Task 11 used in Task 12. All signatures match across tasks.
