import { describe, it, expect } from "vitest";
import { CARDS, activeIdFor, chromeLabelFor, accentFor, IDLE_ACCENT } from "../sources";

describe("sources catalogue", () => {
  it("lists every input the boombox can play, in Home order", () => {
    expect(CARDS.map(c => c.id)).toEqual([
      "mopidy", "movies", "airplay", "spotify", "bluetooth", "aux",
    ]);
  });

  it("gives every card an accent and a glyph so tiles never render bare", () => {
    for (const c of CARDS) {
      expect(c.accent).toMatch(/^#/);
      expect(c.name.length).toBeGreaterThan(0);
    }
  });
});

describe("activeIdFor", () => {
  it("maps shairport to airplay while it is live", () => {
    expect(activeIdFor("ShairportSync", "playing", false)).toBe("airplay");
    expect(activeIdFor("shairport-sync", "paused", false)).toBe("airplay");
  });

  it("maps librespot/raspotify to spotify", () => {
    expect(activeIdFor("librespot", "playing", false)).toBe("spotify");
    expect(activeIdFor("raspotify", "playing", false)).toBe("spotify");
  });

  it("maps bluez to bluetooth", () => {
    expect(activeIdFor("bluez_player_AA_BB", "playing", false)).toBe("bluetooth");
  });

  it("ignores a stopped external player and falls back to Mopidy", () => {
    expect(activeIdFor("ShairportSync", "stopped", true)).toBe("mopidy");
    expect(activeIdFor("ShairportSync", "stopped", false)).toBeNull();
  });

  it("returns null when nothing is producing audio", () => {
    expect(activeIdFor(null, "stopped", false)).toBeNull();
  });
});

describe("chrome identity helpers", () => {
  it("labels Mopidy LIBRARY and nothing IDLE (unchanged chrome copy)", () => {
    expect(chromeLabelFor("mopidy")).toBe("LIBRARY");
    expect(chromeLabelFor("airplay")).toBe("AIRPLAY");
    expect(chromeLabelFor(null)).toBe("IDLE");
  });

  it("falls back to the idle accent when no source is live", () => {
    expect(accentFor(null)).toBe(IDLE_ACCENT);
    expect(accentFor("spotify")).toBe(CARDS.find(c => c.id === "spotify")!.accent);
  });
});
