// Every skin's player view must expose a Library entry (ChromeApi.onOpenLibrary):
// HomeScreen's Music tile only opens the library while nothing is queued, so
// the player chrome is the only way to browse while music is lined up.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, within } from "@testing-library/react";
import { SKINS, type ChromeApi } from "../../lib/skinRegistry";
import { ChromeButtons } from "../../lib/ChromeButtons";
import { SimpleAudio } from "../simple/Simple";
import { Block95Audio } from "../block95/Block95";
import type { Track } from "../../lib/types";

function makeChrome(over: Partial<ChromeApi> = {}): ChromeApi {
  return {
    sourceLabel: "LIBRARY",
    sourceColor: "#9bf2c0",
    sourceLive: false,
    queueCount: 3,
    skinName: "Test",
    onGoHome: vi.fn(),
    onOpenQueue: vi.fn(),
    onOpenLibrary: vi.fn(),
    onOpenSkinPicker: vi.fn(),
    onOpenSettings: vi.fn(),
    ...over,
  };
}

const TRACK: Track = {
  uri: "local:track:1", artist: "Artist", title: "Title", album: "Album",
  time: "3:00", len: 180, hue: 120,
};

beforeEach(() => {
  // Skins mount SyncIndicator (polls the library service) and the spectrum
  // socket; keep both inert under jsdom.
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  vi.stubGlobal("WebSocket", class {
    static OPEN = 1; static CONNECTING = 0;
    readyState = 0;
    close() {}
  });
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("Library entry in skin chrome", () => {
  it.each(SKINS.map(s => [s.id, s] as const))("%s renders a Library control", (_id, skin) => {
    const { Audio } = skin;
    const { getAllByRole } = render(
      <Audio track={TRACK} state="playing" elapsed={10} volume={50} chrome={makeChrome()}/>,
    );
    expect(getAllByRole("button", { name: /library/i }).length).toBeGreaterThan(0);
  });

  it.each(SKINS.map(s => [s.id, s] as const))("%s: tapping Library calls onOpenLibrary", (_id, skin) => {
    const chrome = makeChrome();
    const { Audio } = skin;
    const { getAllByRole } = render(
      <Audio track={TRACK} state="paused" elapsed={0} volume={50} chrome={chrome}/>,
    );
    // Exact name: Simple's Home item shows the source ("Home · LIBRARY") but
    // is labelled "Home", so only the real Library entry matches.
    const [lib] = getAllByRole("button", { name: "Library" });
    fireEvent.click(lib);
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenQueue).not.toHaveBeenCalled();
  });

  it("Simple: the Library nav item opens the library", () => {
    const chrome = makeChrome();
    const { container } = render(
      <SimpleAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={chrome}/>,
    );
    // The sidebar nav item sits next to Queue.
    const nav = container.querySelectorAll("button");
    const labels = Array.from(nav).map(b => b.textContent ?? "");
    const libIdx = labels.findIndex(l => /^Library/.test(l));
    const queueIdx = labels.findIndex(l => /^Queue/.test(l));
    expect(libIdx).toBeGreaterThanOrEqual(0);
    expect(Math.abs(libIdx - queueIdx)).toBe(1);
    fireEvent.click(nav[libIdx]);
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
  });

  it("Block95: the chrome Library button opens the library", () => {
    const chrome = makeChrome();
    const { getByLabelText } = render(
      <Block95Audio track={TRACK} state="playing" elapsed={10} volume={50} chrome={chrome}/>,
    );
    fireEvent.click(getByLabelText("Library"));
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
  });

  it("<ChromeButtons/> strip includes a Library button wired to onOpenLibrary", () => {
    const chrome = makeChrome();
    const { container } = render(<ChromeButtons chrome={chrome}/>);
    fireEvent.click(within(container).getByRole("button", { name: /library/i }));
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
  });
});
