// Registry of every skin's NowPlaying ("Audio") component. The App
// looks up the active skin id and renders the matching component, all of
// which share the same prop interface so swapping is trivial.

import type { ComponentType } from "react";
import type { SkinId, Track, PlayState } from "./types";

import { DeckosAudio } from "../skins/deckos/DeckOS";
import { Block95Audio } from "../skins/block95/Block95";
import { SimpleAudio } from "../skins/simple/Simple";
import { MeterAudio } from "../skins/meter/Meter";
import { SpectrumAudio } from "../skins/spectrum/Spectrum";
import { TapeshiftAudio } from "../skins/tapeshift/Tapeshift";

/** Skin-chrome API: identity + actions a skin needs to integrate its chrome
 * with the rest of the boombox (source switching, queue, skin picker). Each
 * skin renders these as part of its own top bar / nav / status row, in its
 * own visual style — they replace the previous floating overlay pills.
 *
 * sourceColor is the accent color for the active source's dot indicator,
 * provided so skins can tint their chrome consistently. */
export type ChromeApi = {
  sourceLabel: string;     // "LIBRARY", "AIRPLAY", "SPOTIFY", "BLUETOOTH", "IDLE"
  sourceColor: string;     // hex accent for that source
  sourceLive: boolean;     // true when an external (non-Mopidy) source is producing audio
  queueCount: number;      // length of the Mopidy tracklist (0 if unknown)
  skinName: string;        // human-readable skin name
  onOpenSource: () => void;
  onOpenQueue: () => void;
  onOpenSkinPicker: () => void;
  onOpenSettings: () => void;
};

export type SkinAudioProps = {
  track: Track | null;
  state: PlayState;
  elapsed: number;
  volume: number | null;
  shuffle?: boolean;
  repeat?: boolean;
  chrome?: ChromeApi;
  onToggle?: () => void;
  onNext?: () => void;
  onPrev?: () => void;
  onToggleShuffle?: () => void;
  onToggleRepeat?: () => void;
  /** Seek to a position in seconds within the current track. Skins should
   * call this when the user taps/drags their progress bar. */
  onSeek?: (positionSec: number) => void;
};

/** Public palette every skin exposes for chrome / external surfaces (the
 * upload page, future remote control, etc.) so they can match visually. */
export type SkinTheme = {
  bg:       string;   // page background
  panel:    string;   // elevated surface (cards, drawers)
  ink:      string;   // primary text on bg/panel
  ink2:     string;   // secondary / muted text
  accent:   string;   // primary call-to-action / highlight
  accent2:  string;   // secondary highlight
  rule:     string;   // hairline borders
  font:     string;   // body font stack
  mono:     string;   // mono font stack
};

export type SkinMeta = {
  id: SkinId;
  name: string;
  blurb: string;
  swatch: string[];      // 3-4 representative colors for the picker thumbnail
  theme: SkinTheme;      // exported so external pages can match this skin
  Audio: ComponentType<SkinAudioProps>;
};

const INTER = "'Inter', system-ui, -apple-system, sans-serif";
const MONO  = "'JetBrains Mono', ui-monospace, monospace";
const ARCHIVO = "'Archivo Black', system-ui, sans-serif";
const SPACE = "'Space Grotesk', system-ui, sans-serif";

export const SKINS: SkinMeta[] = [
  {
    id: "deckos",
    name: "Deck//OS",
    blurb: "Cyberpunk tape-deck terminal · phosphor green + magenta",
    swatch: ["#0a0e0c", "#9bf2c0", "#ff4fa8", "#5be9ff"],
    theme: {
      bg: "#0a0e0c", panel: "#11171a", ink: "#d8ffe6", ink2: "#7aa492",
      accent: "#9bf2c0", accent2: "#ff4fa8",
      rule: "rgba(155,242,192,0.15)",
      font: MONO, mono: MONO,
    },
    Audio: DeckosAudio,
  },
  {
    id: "block95",
    name: "Block 95",
    blurb: "Chunky 90s portable plastic · flat blocks",
    swatch: ["#0c0c0c", "#ffd400", "#ff2d8a", "#00d3e6"],
    theme: {
      bg: "#0c0c0c", panel: "#1a1a1a", ink: "#fafaf6", ink2: "#9c9c93",
      accent: "#ffd400", accent2: "#ff2d8a",
      rule: "rgba(255,255,255,0.10)",
      font: ARCHIVO, mono: MONO,
    },
    Audio: Block95Audio,
  },
  {
    id: "simple",
    name: "Simple",
    blurb: "Clean dark streaming app · terminal accents",
    swatch: ["#07060c", "#8b5cf6", "#5be7ff", "#a78bfa"],
    theme: {
      bg: "#07060c", panel: "#100d1c", ink: "#f3f1ff", ink2: "#9892b8",
      accent: "#8b5cf6", accent2: "#5be7ff",
      rule: "rgba(255,255,255,0.08)",
      font: INTER, mono: MONO,
    },
    Audio: SimpleAudio,
  },
  {
    id: "meter",
    name: "Meter",
    blurb: "Vintage VU/gauge worship · cream paper + amber",
    swatch: ["#ece6d8", "#16140e", "#e26a1f", "#c93a2a"],
    theme: {
      bg: "#ece6d8", panel: "#f4efe2", ink: "#16140e", ink2: "#5a5345",
      accent: "#e26a1f", accent2: "#c93a2a",
      rule: "#cdc5b1",
      font: SPACE, mono: MONO,
    },
    Audio: MeterAudio,
  },
  {
    id: "spectrum",
    name: "Spectrum",
    blurb: "Visualizer-first immersive · radial spectrum",
    swatch: ["#070a14", "#5be7ff", "#b794ff", "#ffb84d"],
    theme: {
      bg: "#070a14", panel: "#0e1424", ink: "#e8f0ff", ink2: "#7d88a8",
      accent: "#5be7ff", accent2: "#b794ff",
      rule: "rgba(91,231,255,0.14)",
      font: INTER, mono: MONO,
    },
    Audio: SpectrumAudio,
  },
  {
    id: "tapeshift",
    name: "Tape//Shift",
    blurb: "Horizontal reel of tracks · cassette-as-data",
    swatch: ["#161410", "#ff7a35", "#c8e44a", "#7fd9d4"],
    theme: {
      bg: "#161410", panel: "#211c16", ink: "#f4ecdc", ink2: "#9e947f",
      accent: "#ff7a35", accent2: "#c8e44a",
      rule: "rgba(255,122,53,0.18)",
      font: INTER, mono: MONO,
    },
    Audio: TapeshiftAudio,
  },
];

export const SKIN_BY_ID: Record<SkinId, SkinMeta> = Object.fromEntries(
  SKINS.map(s => [s.id, s])
) as Record<SkinId, SkinMeta>;
