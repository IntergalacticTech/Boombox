// sources.ts — the single catalogue of inputs the boombox can play.
//
// Four of these (Mopidy, AirPlay, Spotify Connect, Bluetooth A2DP) are passive
// parallel receivers running side-by-side on PipeWire; boombox-state surfaces
// whichever non-Mopidy MPRIS player is "active". Movies swaps the kiosk to
// Jellyfin, and AUX is physical-only (no Pi-side detection at all).
//
// This lives apart from any component because two surfaces need the same
// facts: the Home screen renders a tile per card, and every skin's chrome
// renders a live-source label + dot. They used to disagree (SourceSwitcher
// had one copy of the matching rules, App.tsx another); one list is the fix.

export type SourceId = "mopidy" | "movies" | "airplay" | "spotify" | "bluetooth" | "aux";

export type SourceCard = {
  id: SourceId;
  name: string;
  tag: string;
  blurb: string;
  accent: string;
  glyph: string;
};

/** Order here is the order of the Home tiles. */
export const CARDS: SourceCard[] = [
  {
    id: "mopidy",
    name: "Music",
    tag: "BUILT-IN",
    blurb: "Local music, playlists, internet radio",
    accent: "#5be7ff",
    glyph: "♪",
  },
  {
    id: "movies",
    name: "Video",
    tag: "JELLYFIN",
    blurb: "Open Jellyfin on the touchscreen. A return pill appears top-left so you can come back here. Music pauses while video plays.",
    accent: "#ff7a35",
    glyph: "▶",
  },
  {
    id: "airplay",
    name: "AirPlay",
    tag: "iOS / macOS",
    blurb: "Pick “Boombox” from the AirPlay menu on your iPhone, iPad, or Mac",
    accent: "#a78bfa",
    glyph: "",
  },
  {
    id: "spotify",
    name: "Spotify",
    tag: "Connect",
    blurb: "Pick “Boombox” under Devices in any Spotify app",
    accent: "#1ed760",
    glyph: "♫",
  },
  {
    id: "bluetooth",
    name: "Bluetooth",
    tag: "A2DP",
    blurb: "Pair any phone or laptop to “Boombox” via Bluetooth",
    accent: "#5b9aff",
    glyph: "✦",
  },
  {
    // AUX is a physical-only source — there's no Pi-side detection or
    // auto-switch. The user flips it on at the amplifier; we just surface it
    // so the picker is honest about what's wired up.
    id: "aux",
    name: "AUX",
    tag: "Line-in",
    blurb: "Plug a 3.5 mm cable into the amplifier’s AUX jack and switch the amp to AUX",
    accent: "#f5a524",
    glyph: "◎",
  },
];

export const CARD_BY_ID: Record<SourceId, SourceCard> = Object.fromEntries(
  CARDS.map(c => [c.id, c])
) as Record<SourceId, SourceCard>;

/** Dot colour when nothing is producing audio. */
export const IDLE_ACCENT = "rgba(255,255,255,0.35)";

/**
 * Which source is actually producing audio right now, or null for silence.
 * An external MPRIS player only counts while it is playing/paused — a
 * lingering stopped shairport process must not claim the chrome.
 */
export function activeIdFor(
  extSource: string | null,
  extStatus: string,
  mopidyPlaying: boolean,
): SourceId | null {
  const live = extStatus === "playing" || extStatus === "paused";
  if (live && extSource) {
    const s = extSource.toLowerCase();
    if (s.includes("shairport") || s.includes("airplay")) return "airplay";
    if (s.includes("spotify") || s.includes("librespot") || s.includes("raspotify")) return "spotify";
    if (s.includes("bluez") || s.includes("blue")) return "bluetooth";
  }
  return mopidyPlaying ? "mopidy" : null;
}

/** Chrome copy. Mopidy reads as "LIBRARY" there (it's the built-in catalogue),
 * even though its Home tile is called Music. */
export function chromeLabelFor(id: SourceId | null): string {
  if (!id) return "IDLE";
  if (id === "mopidy") return "LIBRARY";
  return id.toUpperCase();
}

export function accentFor(id: SourceId | null): string {
  return id ? CARD_BY_ID[id].accent : IDLE_ACCENT;
}

/** True when a non-Mopidy receiver has taken over the speakers. */
export function isExternalId(id: SourceId | null): boolean {
  return id !== null && id !== "mopidy";
}
