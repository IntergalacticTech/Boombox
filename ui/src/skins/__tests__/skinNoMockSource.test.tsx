// Skins must show the real source (chrome.sourceLabel), not design-mock
// "LOCAL" / "DAC pcm5122" / fake version strings.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render } from "@testing-library/react";
import { SKINS, type ChromeApi } from "../../lib/skinRegistry";
import type { Track } from "../../lib/types";

function makeChrome(over: Partial<ChromeApi> = {}): ChromeApi {
  return {
    sourceLabel: "AIRPLAY", sourceColor: "#5be7ff", sourceLive: false,
    queueCount: 3, skinName: "Test",
    onGoHome: vi.fn(), onOpenQueue: vi.fn(), onOpenLibrary: vi.fn(),
    onOpenSkinPicker: vi.fn(), onOpenSettings: vi.fn(),
    ...over,
  };
}

const TRACK: Track = {
  uri: "local:track:1", artist: "Artist", title: "Title", album: "Album",
  time: "3:00", len: 180, hue: 120,
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  vi.stubGlobal("WebSocket", class {
    static OPEN = 1; static CONNECTING = 0;
    readyState = 0;
    close() {}
  });
});
afterEach(() => { vi.unstubAllGlobals(); });

const FAKES = [/LOCAL/i, /pcm5122/i, /\bDAC\b/, /v0\.4\.1/];

describe("skins show no mock source/device text", () => {
  it.each(SKINS.map(s => [s.id, s] as const))("%s with chrome shows the real source label", (_id, { Audio }) => {
    const { container } = render(
      <Audio track={TRACK} state="playing" elapsed={10} volume={50} chrome={makeChrome()}/>,
    );
    const text = container.textContent ?? "";
    for (const re of FAKES) expect(text).not.toMatch(re);
    expect(text).toContain("AIRPLAY");
  });

  it.each(SKINS.map(s => [s.id, s] as const))("%s without chrome omits the source", (_id, { Audio }) => {
    const { container } = render(
      <Audio track={TRACK} state="playing" elapsed={10} volume={50}/>,
    );
    const text = container.textContent ?? "";
    for (const re of FAKES) expect(text).not.toMatch(re);
  });
});
