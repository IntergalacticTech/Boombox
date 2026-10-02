// Nightstand skin: controls, chrome navigation and the per-state rendering
// from the design (idle, AUX, radio, long text, chrome-less preview).
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, within, waitFor } from "@testing-library/react";
import type { ChromeApi, SkinAudioProps } from "../../lib/skinRegistry";
import { NightstandAudio, NIGHTSTAND_THEME, NIGHTSTAND_SWATCH } from "../nightstand/Nightstand";
import type { Track } from "../../lib/types";

function makeChrome(over: Partial<ChromeApi> = {}): ChromeApi {
  return {
    sourceLabel: "LIBRARY",
    sourceColor: "#3FA7F5",
    sourceLive: false,
    queueCount: 3,
    skinName: "Nightstand",
    onGoHome: vi.fn(),
    onOpenQueue: vi.fn(),
    onOpenLibrary: vi.fn(),
    onOpenSkinPicker: vi.fn(),
    onOpenSettings: vi.fn(),
    ...over,
  };
}

const TRACK: Track = {
  uri: "local:track:1", artist: "Garth Brooks", title: "Friends In Low Places", album: "No Fences",
  time: "4:19", len: 259, hue: 28,
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

function setup(over: Partial<SkinAudioProps> = {}) {
  const props: SkinAudioProps = {
    track: TRACK, state: "playing", elapsed: 67, volume: 62, chrome: makeChrome(),
    onToggle: vi.fn(), onPrev: vi.fn(), onNext: vi.fn(),
    onToggleShuffle: vi.fn(), onToggleRepeat: vi.fn(), onSeek: vi.fn(),
    ...over,
  };
  return { props, ...render(<NightstandAudio {...props}/>) };
}

describe("Nightstand skin", () => {
  it("exports a 9-slot theme and a 3–4 colour swatch", () => {
    expect(Object.keys(NIGHTSTAND_THEME).sort()).toEqual(
      ["accent", "accent2", "bg", "font", "ink", "ink2", "mono", "panel", "rule"]);
    expect(NIGHTSTAND_SWATCH.length).toBeGreaterThanOrEqual(3);
    expect(NIGHTSTAND_SWATCH.length).toBeLessThanOrEqual(4);
  });

  it("renders title, artist, album, times, volume and the state word", () => {
    const { container, getByText } = setup();
    expect(getByText("Friends In Low Places")).toBeInTheDocument();
    expect(getByText("Garth Brooks")).toBeInTheDocument();
    expect(getByText("No Fences")).toBeInTheDocument();
    expect(getByText("PLAYING")).toBeInTheDocument();
    expect(getByText("1:07")).toBeInTheDocument();
    expect(getByText("4:19")).toBeInTheDocument();
    expect(getByText("VOL 62")).toBeInTheDocument();
    const root = container.firstElementChild as HTMLElement;
    expect(root.style.width).toBe("1280px");
    expect(root.style.height).toBe("800px");
    expect(root.style.overflow).toBe("hidden");
  });

  it("the big button toggles play/pause", () => {
    const { props, getByRole, rerender } = setup();
    fireEvent.click(getByRole("button", { name: "Pause" }));
    expect(props.onToggle).toHaveBeenCalledTimes(1);
    rerender(<NightstandAudio {...props} state="paused"/>);
    fireEvent.click(getByRole("button", { name: "Play" }));
    expect(props.onToggle).toHaveBeenCalledTimes(2);
  });

  it("paused: word reads PAUSED and track details drop to 45 %", () => {
    const { getByText, getByTestId } = setup({ state: "paused" });
    expect(getByText("PAUSED")).toBeInTheDocument();
    expect(getByTestId("nightstand-info").style.opacity).toBe("0.45");
  });

  it("prev / next / shuffle / repeat call their handlers", () => {
    const { props, getByRole } = setup({ shuffle: true, repeat: false });
    fireEvent.click(getByRole("button", { name: "Previous" }));
    fireEvent.click(getByRole("button", { name: "Next" }));
    fireEvent.click(getByRole("button", { name: "Shuffle" }));
    fireEvent.click(getByRole("button", { name: "Repeat" }));
    expect(props.onPrev).toHaveBeenCalledTimes(1);
    expect(props.onNext).toHaveBeenCalledTimes(1);
    expect(props.onToggleShuffle).toHaveBeenCalledTimes(1);
    expect(props.onToggleRepeat).toHaveBeenCalledTimes(1);
    expect(getByRole("button", { name: "Shuffle" })).toHaveAttribute("aria-pressed", "true");
    expect(getByRole("button", { name: "Repeat" })).toHaveAttribute("aria-pressed", "false");
  });

  it("Library calls chrome.onOpenLibrary", () => {
    const { props, getByRole } = setup();
    fireEvent.click(getByRole("button", { name: "Library" }));
    expect(props.chrome!.onOpenLibrary).toHaveBeenCalledTimes(1);
    expect(props.chrome!.onOpenQueue).not.toHaveBeenCalled();
  });

  it("Home, Queue, Skin and Settings call their chrome actions and show their data", () => {
    const chrome = makeChrome({ queueCount: 999, sourceLabel: "AIRPLAY" });
    const { getByRole } = setup({ chrome });
    const nav = within(getByRole("navigation"));
    fireEvent.click(nav.getByRole("button", { name: "Home" }));
    fireEvent.click(nav.getByRole("button", { name: "Queue" }));
    fireEvent.click(nav.getByRole("button", { name: "Skin" }));
    fireEvent.click(nav.getByRole("button", { name: "Settings" }));
    expect(chrome.onGoHome).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenQueue).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenSkinPicker).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenSettings).toHaveBeenCalledTimes(1);
    expect(nav.getByRole("button", { name: "Queue" })).toHaveTextContent("999");
    expect(nav.getByRole("button", { name: "Home" })).toHaveTextContent("AIRPLAY");
    expect(nav.getByRole("button", { name: "Skin" })).toHaveTextContent("Nightstand");
  });

  it("queue 0 and 1 render their counts", () => {
    for (const n of [0, 1]) {
      const { getByRole, unmount } = setup({ chrome: makeChrome({ queueCount: n }) });
      expect(getByRole("button", { name: "Queue" })).toHaveTextContent(`Queue${n}`);
      unmount();
    }
  });

  it("track=null renders the idle state without crashing", () => {
    const { getByText, getByRole, queryByText } = setup({
      track: null, state: "stopped", elapsed: 0, chrome: makeChrome({ sourceLabel: "IDLE", queueCount: 0 }),
    });
    expect(getByText("Nothing queued")).toBeInTheDocument();
    expect(getByText("Open the Library to choose music")).toBeInTheDocument();
    expect(getByRole("button", { name: "Play" })).toBeDisabled();
    expect(queryByText("PLAYING")).toBeNull();
    expect(queryByText("PAUSED")).toBeNull();
  });

  it("AUX with no track reads Line-in", () => {
    const { getByText, getAllByText, queryByText } = setup({
      track: null, state: "stopped", elapsed: 0, volume: null, chrome: makeChrome({ sourceLabel: "AUX" }),
    });
    expect(getByText("Line-in")).toBeInTheDocument();
    expect(getAllByText("LINE-IN").length).toBe(1);
    expect(getByText("Playing from the AUX jack")).toBeInTheDocument();
    expect(queryByText(/VOL/)).toBeNull();
  });

  it("external source without album/len/volume renders no times or volume", () => {
    const { getByText, getByTestId, queryByText } = setup({
      track: { ...TRACK, title: "Holocene", artist: "Bon Iver", album: "", len: 0 },
      elapsed: 0, volume: null, chrome: makeChrome({ sourceLabel: "AIRPLAY", sourceLive: true, queueCount: 0 }),
    });
    expect(getByText("Holocene")).toBeInTheDocument();
    expect(getByTestId("nightstand-elapsed")).toHaveTextContent("");
    expect(queryByText(/VOL/)).toBeNull();
  });

  it.each(["AIRPLAY", "SPOTIFY", "BLUETOOTH"])("%s never shows LIVE, even with sourceLive and len 0", (src) => {
    const { queryByText, getByTestId } = setup({
      track: { ...TRACK, title: "Holocene", artist: "Bon Iver", album: "", len: 0 },
      elapsed: 30, volume: null, chrome: makeChrome({ sourceLabel: src, sourceLive: true }),
    });
    expect(queryByText("LIVE")).toBeNull();
    expect(getByTestId("nightstand-elapsed")).toHaveTextContent("");
  });

  it("radio without chrome still shows LIVE", () => {
    const { getAllByText } = setup({
      track: { ...TRACK, album: "", len: 0 }, elapsed: 5, chrome: undefined,
    });
    expect(getAllByText("LIVE").length).toBeGreaterThanOrEqual(1);
  });

  it("chrome undefined doesn't crash and disables navigation", () => {
    const { getByText, getByRole } = setup({ chrome: undefined });
    expect(getByText("Friends In Low Places")).toBeInTheDocument();
    expect(getByRole("button", { name: "Library" })).toBeDisabled();
    expect(getByRole("button", { name: "Settings" })).toBeDisabled();
  });

  it("radio (len 0) disables seek, shows LIVE and counts elapsed up", () => {
    const { props, getByTestId, getAllByText } = setup({
      track: { ...TRACK, title: "Morning Edition", artist: "KEXP 90.3", album: "", len: 0 },
      elapsed: 754,
    });
    const seek = getByTestId("nightstand-seek");
    expect(seek).toHaveAttribute("aria-disabled", "true");
    const bar = seek.firstElementChild as HTMLElement;
    fireEvent.pointerDown(bar, { clientX: 10, pointerId: 1 });
    fireEvent.pointerUp(bar, { clientX: 10, pointerId: 1 });
    expect(props.onSeek).not.toHaveBeenCalled();
    expect(getByTestId("nightstand-elapsed")).toHaveTextContent("12:34");
    expect(getAllByText("LIVE").length).toBeGreaterThanOrEqual(1);
  });

  it("a normal track is seekable", () => {
    const { props, getByTestId } = setup();
    const seek = getByTestId("nightstand-seek");
    expect(seek).toHaveAttribute("aria-disabled", "false");
    const bar = seek.firstElementChild as HTMLElement;
    fireEvent.pointerDown(bar, { clientX: 0, pointerId: 1 });
    fireEvent.pointerUp(bar, { clientX: 0, pointerId: 1 });
    expect(props.onSeek).toHaveBeenCalledTimes(1);
  });

  it("long text renders (clamped title, ellipsised artist/album)", () => {
    const long = {
      ...TRACK,
      title: "The Ballad of the Long Distance Lorry Driver and His Dog Rex",
      artist: "The Extraordinarily Long Named Orchestra",
      album: "Songs From Somewhere Very Far Away Indeed",
    };
    const { getByText } = setup({ track: long, chrome: makeChrome({ queueCount: 999 }) });
    const title = getByText(long.title);
    expect(title.style.webkitLineClamp).toBe("2");
    expect(getByText(long.artist).style.textOverflow).toBe("ellipsis");
    expect(getByText(long.album).style.textOverflow).toBe("ellipsis");
  });

  it("missing art falls back to a hue disc with the album initial", () => {
    const { getByTestId } = setup({ track: { ...TRACK, album: "Harvest Moon", artUrl: undefined } });
    expect(getByTestId("nightstand-art-fallback")).toHaveTextContent("H");
  });

  it("looks up art through the shared /api/art hook when artUrl is absent", async () => {
    const fetchMock = vi.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ url: "/art/cache/abc.jpg" }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const { container, queryByTestId } = setup({
      track: { ...TRACK, uri: "local:track:lookup", artist: "Lookup Artist", album: "Lookup Album" },
    });
    await waitFor(() => expect(container.querySelector("img")?.getAttribute("src")).toBe("/art/cache/abc.jpg"));
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toContain("/api/art?");
    expect(queryByTestId("nightstand-art-fallback")).toBeNull();
  });

  it("uses the real art when provided", () => {
    const { container, queryByTestId } = setup({ track: { ...TRACK, artUrl: "/api/art/1.jpg" } });
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/api/art/1.jpg");
    expect(queryByTestId("nightstand-art-fallback")).toBeNull();
  });

  it("every button has an accessible name", () => {
    const { getAllByRole } = setup();
    for (const b of getAllByRole("button")) {
      expect((b.getAttribute("aria-label") ?? b.textContent ?? "").trim()).not.toBe("");
    }
  });

  it("tracks queued but none loaded shows a ready state with Play enabled", () => {
    const onToggle = vi.fn();
    const chrome = makeChrome({ sourceLabel: "LIBRARY", sourceLive: false, queueCount: 10 });
    const { getByRole, container, rerender } = render(
      <NightstandAudio track={null} state="paused" elapsed={0} volume={50} chrome={chrome} onToggle={onToggle}/>,
    );
    const text = container.textContent ?? "";
    expect(text).toMatch(/ready to play/i);
    expect(text).toMatch(/10 tracks queued/i);
    expect(text).not.toMatch(/nothing queued/i);
    const play = getByRole("button", { name: "Play" });
    expect(play).toBeEnabled();
    // Neither Play nor any ancestor is dimmed.
    for (let el: HTMLElement | null = play; el && el !== container; el = el.parentElement) {
      expect(Number(el.style.opacity || 1)).toBe(1);
    }
    fireEvent.click(play);
    expect(onToggle).toHaveBeenCalledTimes(1);

    rerender(<NightstandAudio track={null} state="paused" elapsed={0} volume={50}
      chrome={makeChrome({ sourceLabel: "LIBRARY", sourceLive: false, queueCount: 1 })} onToggle={onToggle}/>);
    expect(container.textContent).toMatch(/1 track queued/i);
  });
});
