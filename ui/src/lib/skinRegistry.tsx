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

export type SkinMeta = {
  id: SkinId;
  name: string;
  blurb: string;
  swatch: string[];      // 3-4 representative colors for the picker thumbnail
  Audio: ComponentType<SkinAudioProps>;
};

export const SKINS: SkinMeta[] = [
  {
    id: "deckos",
    name: "Deck//OS",
    blurb: "Cyberpunk tape-deck terminal · phosphor green + magenta",
    swatch: ["#0a0e0c", "#9bf2c0", "#ff4fa8", "#5be9ff"],
    Audio: DeckosAudio,
  },
  {
    id: "block95",
    name: "Block 95",
    blurb: "Chunky 90s portable plastic · flat blocks",
    swatch: ["#0c0c0c", "#ffd400", "#ff2d8a", "#00d3e6"],
    Audio: Block95Audio,
  },
  {
    id: "simple",
    name: "Simple",
    blurb: "Clean dark streaming app · terminal accents",
    swatch: ["#07060c", "#8b5cf6", "#5be7ff", "#a78bfa"],
    Audio: SimpleAudio,
  },
  {
    id: "meter",
    name: "Meter",
    blurb: "Vintage VU/gauge worship · cream paper + amber",
    swatch: ["#ece6d8", "#16140e", "#e26a1f", "#c93a2a"],
    Audio: MeterAudio,
  },
  {
    id: "spectrum",
    name: "Spectrum",
    blurb: "Visualizer-first immersive · radial spectrum",
    swatch: ["#070a14", "#5be7ff", "#b794ff", "#ffb84d"],
    Audio: SpectrumAudio,
  },
  {
    id: "tapeshift",
    name: "Tape//Shift",
    blurb: "Horizontal reel of tracks · cassette-as-data",
    swatch: ["#161410", "#ff7a35", "#c8e44a", "#7fd9d4"],
    Audio: TapeshiftAudio,
  },
];

export const SKIN_BY_ID: Record<SkinId, SkinMeta> = Object.fromEntries(
  SKINS.map(s => [s.id, s])
) as Record<SkinId, SkinMeta>;
