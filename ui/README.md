# Boombox Touch UI

Vite + React + TypeScript app rendered by Chromium in kiosk mode. The app is
built for a fixed 1280x800 design space, then scaled to the physical
touchscreen by `ScaleToFit`.

## Development

```bash
npm install
BOOMBOX_DEV_TARGET=http://10.0.5.178:8090 BOOMBOX_WEB_USER=boombox BOOMBOX_WEB_PASSWORD=123456 npm run dev
```

`BOOMBOX_DEV_TARGET` should point at the Pi's authenticated LAN nginx port.
Read the real password with `../pi ssh "sudo cat /etc/boombox/web-auth.env"`.
The Vite dev server proxies `/mopidy`, `/api`, and `/audio` through that
target so local development sees the same paths as the kiosk.

## Build

```bash
npm run build
```

The installer and `boombox-update` deploy `dist/` to `/var/www/boombox/` on
the Pi. Do not commit `dist/` or `node_modules/`.

## Structure

- `src/App.tsx` selects the active skin and wires Mopidy, MPRIS, drawers, and
  global gestures together.
- `src/lib/` contains Mopidy JSON-RPC helpers, drawers, source detection,
  visualizer hooks, album art, favorites, and shared controls.
- `src/skins/` contains runtime skins. Design-time source lives in the repo
  root `skins/` directory.
