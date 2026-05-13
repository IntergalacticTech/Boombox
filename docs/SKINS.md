# Creating a skin

The boombox has **six built-in skins** (Deck//OS, Block 95, Simple, Meter,
Spectrum, Tape//Shift), and the system is designed so adding a new one is
almost entirely a visual exercise: write a single React component that
implements one interface and you're done.

This guide walks through the full process: file layout, the contract the
component has to satisfy, the helpers you get for free, and how to register
your skin so the picker can find it.

---

## TL;DR — add a skin in 6 steps

```
1. Pick an id, e.g.  retro80
2. Add the id to:    ui/src/lib/types.ts (SkinId union)
3. Create folder:    ui/src/skins/retro80/Retro80.tsx
4. Export:           Retro80Audio: ComponentType<SkinAudioProps>
5. Register:         ui/src/lib/skinRegistry.tsx (push into SKINS[])
6. (Optional)        skins/retro80/{source.jsx, tokens.json, README.md}
                     for the design-time mockup
```

Reload the kiosk (`./pi reload`) and the new skin appears in the picker
drawer. Pin it with `?skin=retro80` in the URL or via the picker.

---

## The two skin worlds: design vs. runtime

There are **two** `skins/` directories in this repo. They look similar but
serve different purposes and intentionally do not share code.

```
skins/                       ← DESIGN-TIME (designer source-of-truth)
├── _shared/shared.jsx       <Icon>, demo tracks, fake VU
├── block95/
│   ├── source.jsx           full mockup as one JSX file (no build step)
│   ├── tokens.json          colors / fonts / variants
│   └── README.md
├── fonts.json               license info for every font we use
└── README.md

ui/src/skins/                ← RUNTIME (what the boombox actually renders)
├── block95/Block95.tsx
├── deckos/DeckOS.tsx
├── meter/Meter.tsx
├── simple/Simple.tsx
├── spectrum/Spectrum.tsx
└── tapeshift/Tapeshift.tsx
```

**`/skins/` (design)** is what a designer iterates on. Each skin is a single
self-contained `.jsx` mockup that renders at 1280×800. No build, no install,
no React-dev-tools. You open `index.html` (an in-repo design canvas, not
checked in here yet) or screenshot it directly. The fonts are listed with
license URLs in `fonts.json` (all OFL-1.1, embed freely).

**`/ui/src/skins/` (runtime)** is the live boombox UI. Each skin is a `.tsx`
component that subscribes to real Mopidy/MPRIS state via the hooks in
`ui/src/lib/`. This is the only directory that ships in the built SPA.

When you add a new skin, the **runtime** entry is mandatory; the **design**
entry is optional but recommended for keeping the design canvas in sync.

---

## The runtime contract

Every runtime skin exports a single React component that takes
`SkinAudioProps` (from [`ui/src/lib/skinRegistry.tsx`](../ui/src/lib/skinRegistry.tsx)):

```ts
export type SkinAudioProps = {
  track:    Track | null;     // null = nothing loaded
  state:    PlayState;        // "playing" | "paused" | "stopped"
  elapsed:  number;           // seconds into the track
  volume:   number | null;    // 0..100 (null = unknown / external source)
  shuffle?: boolean;
  repeat?:  boolean;
  chrome?:  ChromeApi;        // skin-chrome actions (see below)

  onToggle?:        () => void;
  onNext?:          () => void;
  onPrev?:          () => void;
  onToggleShuffle?: () => void;
  onToggleRepeat?:  () => void;
  onSeek?:          (positionSec: number) => void;
};
```

A `Track` is just metadata:

```ts
type Track = {
  uri: string;        // mopidy/spotify/airplay uri
  artist: string;
  title: string;
  album: string;
  time: string;       // "3:48" — pre-formatted for display
  len: number;        // 228   — seconds
  hue: number;        // 0..360 — fallback gradient color
  artUrl?: string;    // resolved cover-art URL, if found
};
```

You don't need to wire up Mopidy or MPRIS yourself — `App.tsx` does that and
passes the unified state to whichever skin is active. Your skin renders the
result; the user's taps call back into the supplied handlers.

### The chrome contract

The `chrome` prop is how a skin renders source-switching, queue, picker, and
settings buttons **in its own visual style** (some skins put them in a top
bar, some in a sidebar, some in a docked footer). It's effectively a small
RPC for opening the global drawers:

```ts
export type ChromeApi = {
  sourceLabel:       string;       // "LIBRARY" | "AIRPLAY" | "SPOTIFY" | "BLUETOOTH" | "IDLE"
  sourceColor:       string;       // hex accent for that source's dot
  sourceLive:        boolean;      // true when an external source is producing audio
  queueCount:        number;       // tracklist length (0 when unknown)
  skinName:          string;       // human-readable name of the active skin
  onOpenSource:      () => void;
  onOpenQueue:       () => void;
  onOpenSkinPicker:  () => void;
  onOpenSettings:    () => void;
};
```

You can either roll your own buttons (recommended — that's the point of a
distinct skin) or drop in the prebuilt strip:

```tsx
import {
  ChromeSourceBtn, ChromeQueueBtn, ChromeSkinBtn, ChromeSettingsBtn,
} from "../../lib/ChromeButtons";

<ChromeSourceBtn   chrome={chrome} theme={myTheme}/>
<ChromeQueueBtn    chrome={chrome} theme={myTheme}/>
<ChromeSkinBtn     chrome={chrome} theme={myTheme}/>
<ChromeSettingsBtn chrome={chrome} theme={myTheme}/>
```

The `theme` prop lets you control bg, fg, border, font, height, radius, and
padding so the chrome dissolves into whatever frame your skin builds.

### Layout target

Skins render into a **fixed 1280×800 design space**. `ScaleToFit` (in
`App.tsx`) scales the whole component to the actual viewport (typically a
1024×600 or 800×480 touchscreen), so you can size everything in absolute
pixels and trust the result will look right.

Don't try to support multiple resolutions inside the skin — work in 1280×800
and the harness scales for you.

---

## Shared helpers you can use

All exported from [`ui/src/lib/shared.tsx`](../ui/src/lib/shared.tsx):

| Export | What it does |
|--------|--------------|
| `<Icon name="play" />` | ~30 single-color SVG icons (`play`, `pause`, `next`, `prev`, `shuffle`, `repeat`, `vol`, `search`, `queue`, `hd`, `bt`, `cast`, `airplay`, `spot`, `radio`, `power`, `settings`, `eq`…) |
| `useTicker(ms)` | Returns a counter that increments on an interval. Use for blinking cursors, fake-VU animation. |
| `vu(t, seed)` | Generates a smooth pseudo-random 0..1 value driven by `t`. Cheap fake VU for non-spectrum visuals. |
| `mmss(s)` | Format seconds as `m:ss`. |
| `TRACKS` | Demo tracklist for mockups. |
| `SOURCES` | Demo source list for mockups. |

And from elsewhere in `ui/src/lib/`:

| Module | What it does |
|--------|--------------|
| `useSpectrum()` (in `spectrum.ts`) | Subscribes to the real audio visualizer WebSocket (`/audio/ws`). Returns `{ bins: number[64], peaks: number[64], rms: [L, R] }`. Updates ~20 Hz. |
| `<SeekableBar value lengthSec onSeek/>` (in `SeekableBar.tsx`) | Draggable/tappable progress bar with a configurable hit area. Wraps your bar shape via `children`. |
| `<AlbumThumb artist album track size/>` (in `AlbumThumb.tsx`) | Renders album art (resolved via `/api/art`) with a hue-tinted gradient fallback. |

---

## The overlay layer (don't reimplement)

`ui/src/overlays/OverlayRoot.tsx` mounts globally **above** the active skin
and handles five pieces of UI that should look the same regardless of the
skin you're running:

| Overlay | Fires on | What it shows |
|---------|----------|---------------|
| `SleepOsd` | `boombox:sleep-timer` / `boombox:sleep-expired` | Pill toast top-center with current sleep duration; auto-hides 2 s after the last update |
| `RecordIndicator` | `boombox:record` | Pulsing red `REC ●` dot top-right while recording |
| `QrOverlay` | `boombox:web-qr` | Full-screen QR + LAN URL + PIN for the upload portal |
| `SourceInstructionOverlay` | `boombox:source-overlay` | Full-screen pairing copy for AirPlay / Spotify / Bluetooth |
| `ShutdownOverlay` | `boombox:shutdown-countdown` / `boombox:shutdown-confirm` | 2 s "release to cancel" countdown for the power button |

The events are dispatched by `boombox-buttons` via Chromium DevTools; the
overlay components listen on `window.addEventListener('boombox:<event>')`.

**Skin rules:**

1. **Don't reimplement these.** A skin that draws its own sleep pill or REC
   dot will double up with the overlay layer. Lean on the global overlays.
2. **Don't draw anything that competes with z-index 9997+** unless you mean
   to (ShutdownOverlay uses 10000 so an in-progress power-off can't be
   hidden by a skin's modal).
3. **Source-switching, pairing, and QR are not the skin's job.** The skin
   only renders Now-Playing + chrome (source / queue / picker / settings
   buttons via `ChromeApi`). The overlays handle the transient stuff.

If you need a new overlay (e.g. a "USB drive mounted" toast that should
work across skins), add it to `ui/src/overlays/` alongside the others and
register the `boombox:<event>` it listens for — don't bury it inside one
skin.

---

## Step-by-step: build "retro80"

### 1. Add the id to the union

`ui/src/lib/types.ts`:

```ts
export type SkinId =
  | "deckos" | "block95" | "simple" | "meter" | "spectrum" | "tapeshift"
  | "retro80";   // ← new
```

This unlocks autocomplete and makes `App.tsx`'s `getActiveSkin()` accept your
id from `?skin=retro80` and from `localStorage`.

### 2. Make the runtime component

`ui/src/skins/retro80/Retro80.tsx`:

```tsx
import { Icon, useTicker, mmss } from "../../lib/shared";
import { SeekableBar } from "../../lib/SeekableBar";
import {
  ChromeSourceBtn, ChromeQueueBtn, ChromeSkinBtn, ChromeSettingsBtn,
} from "../../lib/ChromeButtons";
import type { SkinAudioProps } from "../../lib/skinRegistry";

const R = {
  bg:    "#1d0e2a",
  panel: "#2a1844",
  ink:   "#f8eaff",
  pink:  "#ff66c4",
  cyan:  "#4fe1ff",
  font:  "'Archivo Black', system-ui, sans-serif",
  mono:  "'JetBrains Mono', monospace",
};

export function Retro80Audio({
  track, state, elapsed, chrome, onToggle, onNext, onPrev, onSeek,
}: SkinAudioProps) {
  const t = useTicker(500);

  return (
    <div style={{
      width: 1280, height: 800,
      background: `linear-gradient(180deg, ${R.bg}, #0b0518)`,
      color: R.ink, fontFamily: R.font, overflow: "hidden",
    }}>
      {/* top chrome */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "20px 32px", borderBottom: `1px solid ${R.pink}40`,
      }}>
        <span style={{ fontSize: 22, letterSpacing: "0.2em", color: R.pink }}>
          ▮ RETRO80
        </span>
        <span style={{ flex: 1 }} />
        {chrome && <>
          <ChromeSourceBtn   chrome={chrome} theme={{ bg: R.panel, fg: R.ink, border: R.pink }}/>
          <ChromeQueueBtn    chrome={chrome} theme={{ bg: R.panel, fg: R.ink, border: R.pink }}/>
          <ChromeSkinBtn     chrome={chrome} theme={{ bg: R.panel, fg: R.ink, border: R.pink }}/>
          <ChromeSettingsBtn chrome={chrome} theme={{ bg: R.panel, fg: R.ink, border: R.pink }}/>
        </>}
      </div>

      {/* now playing */}
      <div style={{ padding: "60px 80px" }}>
        <div style={{ fontSize: 72, letterSpacing: "-0.02em" }}>
          {track?.title ?? "—"}
        </div>
        <div style={{ fontSize: 28, color: R.cyan, marginTop: 12 }}>
          {track?.artist ?? "—"} · {track?.album ?? ""}
        </div>

        <SeekableBar
          value={track ? elapsed / track.len : 0}
          lengthSec={track?.len ?? 0}
          onSeek={onSeek}
          style={{ marginTop: 60, height: 8, background: `${R.pink}30` }}
        >
          <div style={{ height: "100%", background: R.pink, width: `${(track ? elapsed/track.len : 0)*100}%` }}/>
        </SeekableBar>

        <div style={{ fontFamily: R.mono, marginTop: 8, color: R.cyan }}>
          {mmss(elapsed)} / {mmss(track?.len ?? 0)}{t % 2 ? "_" : " "}
        </div>

        <div style={{ display: "flex", gap: 24, marginTop: 60 }}>
          <button onClick={onPrev}><Icon name="prev"   size={56} stroke={R.ink}/></button>
          <button onClick={onToggle}><Icon name={state === "playing" ? "pause" : "play"} size={72} stroke={R.pink}/></button>
          <button onClick={onNext}><Icon name="next"   size={56} stroke={R.ink}/></button>
        </div>
      </div>
    </div>
  );
}
```

### 3. Register the skin

`ui/src/lib/skinRegistry.tsx`:

```tsx
import { Retro80Audio } from "../skins/retro80/Retro80";

// …

export const SKINS: SkinMeta[] = [
  // …existing skins…
  {
    id: "retro80",
    name: "Retro80",
    blurb: "Synthwave neon — pink + cyan on aubergine",
    swatch: ["#1d0e2a", "#ff66c4", "#4fe1ff", "#f8eaff"],
    Audio: Retro80Audio,
  },
];
```

`swatch` is the 3–4 color preview the picker shows. Use the same hex values
your skin uses for chrome / accent / background.

### 4. Test

```bash
cd ui
npm run dev
# open http://localhost:5173/?skin=retro80
```

For dev against real Pi state, set the Vite proxy target in
`ui/vite.config.ts` to your Pi (already there). You'll see real Mopidy +
MPRIS state stream into your skin while you edit.

To deploy to the Pi:

```bash
# from repo root
cd ui && npm run build
../pi deploy ui/dist/ /var/www/boombox/
../pi reload
```

Or just `boombox-update` on the Pi if the skin is committed and pushed.

---

## Optional: a design-time mockup

If you want a design-canvas entry to iterate on with no build step, mirror
the runtime under `skins/retro80/`:

```
skins/retro80/
├── source.jsx       full mockup in one file (uses _shared/shared.jsx via window globals)
├── tokens.json      see existing skins for shape
└── README.md
```

The `tokens.json` file is structured but loosely enforced. Treat it as:

```jsonc
{
  "id": "retro80",
  "name": "Retro80",
  "description": "Synthwave neon — pink + cyan on aubergine",
  "palette": {
    "bg":      "#1d0e2a",
    "panel":   "#2a1844",
    "ink":     "#f8eaff",
    "primary": "#ff66c4",
    "accent":  "#4fe1ff"
  },
  "fonts": {
    "display": "Archivo Black",
    "body":    "Inter",
    "mono":    "JetBrains Mono"
  },
  "fontLicenses": {
    "Archivo Black": { "license": "OFL-1.1", "url": "https://github.com/Omnibus-Type/Archivo" },
    "Inter":         { "license": "OFL-1.1", "url": "https://github.com/rsms/inter" },
    "JetBrains Mono":{ "license": "OFL-1.1", "url": "https://github.com/JetBrains/JetBrainsMono" }
  }
}
```

Fonts must be libre (currently every shipping skin uses OFL-1.1 fonts —
keep that going so we don't have to track per-font attribution).

---

## Design guidelines (soft rules)

These come from running the existing six skins on a 5″ 800×480 panel:

1. **Big touch targets.** ≥48 px on screen → ≥80 px in 1280×800 design space.
2. **Live state visible at a glance.** Title + artist must be readable
   from 3 m away in the dimmest lighting your boombox might live in.
3. **One distinct accent color.** Skins that drift toward "generic dark UI"
   blur together. The accent is what makes a skin recognizable.
4. **Don't fight the chrome.** Either render the chrome buttons (recommended)
   or accept that the user can still open drawers via the bezel gesture
   stubs in `App.tsx`.
5. **No real-time work in render.** If you need an animation, drive it from
   `useTicker` or `useSpectrum`. Don't run an FPS loop in your component
   body; you'll burn the Pi's GPU.
6. **Test with stopped state.** A skin that only looks good with a track
   loaded will spend 30 % of its life looking broken. Render something
   intentional when `track === null` or `state === "stopped"`.

---

## Cheat sheet: where every file lives

```
ui/src/lib/types.ts           ← add SkinId
ui/src/lib/skinRegistry.tsx   ← register SKINS[]
ui/src/skins/<id>/<Id>.tsx    ← your component (default-exports… no, named)
ui/src/lib/shared.tsx         ← Icon, useTicker, vu, mmss, TRACKS
ui/src/lib/spectrum.ts        ← useSpectrum()
ui/src/lib/SeekableBar.tsx    ← <SeekableBar/>
ui/src/lib/AlbumThumb.tsx     ← <AlbumThumb/>
ui/src/lib/ChromeButtons.tsx  ← prebuilt chrome buttons
skins/<id>/                   ← optional design-time mockup
```

That's the whole story. Skins are intentionally cheap to add — the harder
problem is having something interesting to express.
