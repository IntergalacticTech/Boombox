export type Track = {
  uri: string;
  artist: string;
  title: string;
  album: string;
  time: string;       // mm:ss display
  len: number;        // seconds
  hue: number;        // for placeholder art gradients
  artUrl?: string;    // resolved album art (if any)
};

export type PlayState = "playing" | "paused" | "stopped";

export type Source = {
  id: string;
  label: string;
  sub: string;
  icon: string;
};

export type SkinId = "deckos" | "block95" | "simple" | "meter" | "spectrum" | "tapeshift";
