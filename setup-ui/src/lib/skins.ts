// The kiosk's skin catalog, mirrored for the wizard's Skin step. Source of
// truth is ui/src/lib/skinRegistry.tsx (id/name/blurb/swatch) — keep in sync
// when a skin is added. The wizard only needs the metadata, not the React
// components, so this stays a tiny standalone list.

export interface SkinChoice {
  id: string;
  name: string;
  blurb: string;
  /** [bg, accent, accent2, extra] display swatch, from the skin's theme. */
  swatch: [string, string, string, string];
}

export const SKIN_CHOICES: SkinChoice[] = [
  {
    id: "deckos",
    name: "Deck//OS",
    blurb: "Cyberpunk tape-deck terminal · phosphor green + magenta",
    swatch: ["#0a0e0c", "#9bf2c0", "#ff4fa8", "#5be9ff"],
  },
  {
    id: "block95",
    name: "Block 95",
    blurb: "Chunky 90s portable plastic · flat blocks",
    swatch: ["#0c0c0c", "#ffd400", "#ff2d8a", "#00d3e6"],
  },
  {
    id: "simple",
    name: "Simple",
    blurb: "Clean dark streaming app · terminal accents",
    swatch: ["#07060c", "#8b5cf6", "#5be7ff", "#a78bfa"],
  },
  {
    id: "meter",
    name: "Meter",
    blurb: "Vintage VU/gauge worship · cream paper + amber",
    swatch: ["#ece6d8", "#16140e", "#e26a1f", "#c93a2a"],
  },
  {
    id: "spectrum",
    name: "Spectrum",
    blurb: "Visualizer-first immersive · radial spectrum",
    swatch: ["#070a14", "#5be7ff", "#b794ff", "#ffb84d"],
  },
  {
    id: "tapeshift",
    name: "Tape//Shift",
    blurb: "Horizontal reel of tracks · cassette-as-data",
    swatch: ["#161410", "#ff7a35", "#c8e44a", "#7fd9d4"],
  },
];

export const DEFAULT_SKIN = "deckos";
