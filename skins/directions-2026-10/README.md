# Six new directions (2026-10)

Imported from the claude.ai/design project "Boombox Skins"
(`b4f018f6-926f-47e3-99a4-4eaf2c27f6cd`), file `Boombox Skins.dc.html` +
its runtime `support.js` (generated; do not edit).

Skins: 1a Departures, 1b Placard, 1c Poster, 1d Nightstand, 1e Pocket LCD,
1f Selector. Each artboard is 1280×800 with ten states (playing, paused,
idle, external, AUX, radio, long text, missing art, shuffle+repeat, queue
empty). Runtime versions live in `ui/src/skins/<id>/`.

View: `python3 -m http.server 8124 -d skins/directions-2026-10` →
http://localhost:8124/Boombox%20Skins.dc.html (needs network for the
design's Google Fonts; the runtime skins bundle their fonts).
