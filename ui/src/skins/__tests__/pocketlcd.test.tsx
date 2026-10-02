// Pocket LCD skin: controls, chrome wiring and the edge states from the design.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import type { ChromeApi } from "../../lib/skinRegistry";
import { PocketLcdAudio, POCKETLCD_THEME, POCKETLCD_SWATCH } from "../pocketlcd/PocketLcd";
import type { Track } from "../../lib/types";

function makeChrome(over: Partial<ChromeApi> = {}): ChromeApi {
  return {
    sourceLabel: "LIBRARY",
    sourceColor: "#3FA7F5",
    sourceLive: false,
    queueCount: 3,
    skinName: "Pocket LCD",
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

const lit = (el: HTMLElement, text: string) =>
  Array.from(el.querySelectorAll<HTMLElement>("[data-lit]")).find(n => n.textContent === text)?.dataset.lit === "true";

describe("Pocket LCD skin", () => {
  it("exports a 9-slot theme and a 3-4 colour swatch", () => {
    for (const k of ["bg", "panel", "ink", "ink2", "accent", "accent2", "rule", "font", "mono"] as const) {
      expect(POCKETLCD_THEME[k]).toBeTruthy();
    }
    expect(POCKETLCD_SWATCH.length).toBeGreaterThanOrEqual(3);
    expect(POCKETLCD_SWATCH.length).toBeLessThanOrEqual(4);
  });

  it("renders title, artist, elapsed and length", () => {
    const { getByText, container } = render(
      <PocketLcdAudio track={TRACK} state="playing" elapsed={67} volume={62} chrome={makeChrome()}/>,
    );
    expect(getByText("Friends In Low Places")).toBeInTheDocument();
    expect(getByText("Garth Brooks")).toBeInTheDocument();
    expect(getByText("01:07")).toBeInTheDocument();
    expect(getByText("/04:19")).toBeInTheDocument();
    expect(container.textContent).toContain("VOL  62");
    expect(lit(container, "PLAY")).toBe(true);
    expect(lit(container, "PAUSE")).toBe(false);
    expect(lit(container, "LIBRARY")).toBe(true);
  });

  it("play/pause calls onToggle and labels follow the state", () => {
    const onToggle = vi.fn();
    const { getByRole, rerender, container } = render(
      <PocketLcdAudio track={TRACK} state="playing" elapsed={10} volume={50} onToggle={onToggle}/>,
    );
    fireEvent.click(getByRole("button", { name: "Pause" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(<PocketLcdAudio track={TRACK} state="paused" elapsed={10} volume={50} onToggle={onToggle}/>);
    fireEvent.click(getByRole("button", { name: "Play" }));
    expect(onToggle).toHaveBeenCalledTimes(2);
    expect(lit(container, "PAUSE")).toBe(true);
    expect(lit(container, "PLAY")).toBe(false);
  });

  it("prev/next/shuffle/repeat call their handlers", () => {
    const h = { onPrev: vi.fn(), onNext: vi.fn(), onToggleShuffle: vi.fn(), onToggleRepeat: vi.fn() };
    const { getByRole } = render(
      <PocketLcdAudio track={TRACK} state="playing" elapsed={10} volume={50} {...h}/>,
    );
    fireEvent.click(getByRole("button", { name: "Previous" }));
    fireEvent.click(getByRole("button", { name: "Next" }));
    fireEvent.click(getByRole("button", { name: "Shuffle" }));
    fireEvent.click(getByRole("button", { name: "Repeat" }));
    expect(h.onPrev).toHaveBeenCalledTimes(1);
    expect(h.onNext).toHaveBeenCalledTimes(1);
    expect(h.onToggleShuffle).toHaveBeenCalledTimes(1);
    expect(h.onToggleRepeat).toHaveBeenCalledTimes(1);
  });

  it("shuffle + repeat light their segments and press their keys", () => {
    const { getByRole, container } = render(
      <PocketLcdAudio track={TRACK} state="playing" elapsed={10} volume={50} shuffle repeat/>,
    );
    expect(getByRole("button", { name: "Shuffle" })).toHaveAttribute("aria-pressed", "true");
    expect(getByRole("button", { name: "Repeat" })).toHaveAttribute("aria-pressed", "true");
    expect(lit(container, "SHUF")).toBe(true);
    expect(lit(container, "RPT")).toBe(true);
  });

  it("Library, Home, Queue, Skin and Settings call their chrome actions", () => {
    const chrome = makeChrome();
    const { getByRole } = render(
      <PocketLcdAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={chrome}/>,
    );
    fireEvent.click(getByRole("button", { name: "Library" }));
    fireEvent.click(getByRole("button", { name: "Home" }));
    fireEvent.click(getByRole("button", { name: "Queue" }));
    fireEvent.click(getByRole("button", { name: "Skin" }));
    fireEvent.click(getByRole("button", { name: "Settings" }));
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
    expect(chrome.onGoHome).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenQueue).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenSkinPicker).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it.each([0, 1, 999])("shows a queue count of %i", n => {
    const { getByRole } = render(
      <PocketLcdAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={makeChrome({ queueCount: n })}/>,
    );
    expect(getByRole("button", { name: "Queue" }).textContent).toBe(`QUEUE${n}`);
  });

  it("track=null renders the idle state, with STOP lit and Open Library", () => {
    const chrome = makeChrome({ sourceLabel: "IDLE", queueCount: 0 });
    const { getByText, getByRole, container } = render(
      <PocketLcdAudio track={null} state="stopped" elapsed={0} volume={50} chrome={chrome}/>,
    );
    expect(getByText("Nothing queued")).toBeInTheDocument();
    expect(lit(container, "STOP")).toBe(true);
    fireEvent.click(getByRole("button", { name: "Open Library" }));
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
  });

  it("AUX line-in with no track shows the line-in state", () => {
    const { getByText, container } = render(
      <PocketLcdAudio track={null} state="stopped" elapsed={0} volume={null}
        chrome={makeChrome({ sourceLabel: "AUX", sourceLive: true })}/>,
    );
    expect(getByText("Line-in")).toBeInTheDocument();
    expect(getByText("AUX in")).toBeInTheDocument();
    expect(lit(container, "AUX")).toBe(true);
    expect(lit(container, "VOL")).toBe(false);
  });

  it("renders without chrome and without handlers", () => {
    const { getByText, queryByText } = render(
      <PocketLcdAudio track={TRACK} state="playing" elapsed={10} volume={50}/>,
    );
    expect(getByText("Friends In Low Places")).toBeInTheDocument();
    expect(queryByText("LIB")).toBeNull();
    const { getByText: g2 } = render(<PocketLcdAudio track={null} state="stopped" elapsed={0} volume={null}/>);
    expect(g2("Nothing queued")).toBeInTheDocument();
  });

  it("shows the real source label and no mock text", () => {
    const { container } = render(
      <PocketLcdAudio track={{ ...TRACK, album: "", len: 0 }} state="playing" elapsed={0} volume={null}
        chrome={makeChrome({ sourceLabel: "AIRPLAY", sourceLive: true, queueCount: 0 })}/>,
    );
    expect(container.textContent).toContain("AIRPLAY");
    expect(lit(container, "AIRPLAY")).toBe(true);
    expect(lit(container, "LIVE")).toBe(false);
    expect(container.textContent).not.toMatch(/LOCAL|DAC|KEXP|COVER ART/);
  });

  it.each(["AIRPLAY", "SPOTIFY", "BLUETOOTH"])("%s (external, len 0, playing) does not light LIVE", src => {
    const { container } = render(
      <PocketLcdAudio track={{ ...TRACK, album: "", len: 0 }} state="playing" elapsed={30} volume={null}
        chrome={makeChrome({ sourceLabel: src, sourceLive: true })}/>,
    );
    expect(lit(container, "LIVE")).toBe(false);
    expect(lit(container, src)).toBe(true);
  });

  it("radio without chrome still lights LIVE", () => {
    const { container } = render(
      <PocketLcdAudio track={{ ...TRACK, len: 0 }} state="playing" elapsed={5} volume={50}/>,
    );
    expect(lit(container, "LIVE")).toBe(true);
  });

  it("radio (len 0) disables seek, lights LIVE and counts elapsed up", () => {
    const onSeek = vi.fn();
    const { getByTestId, getByText, container } = render(
      <PocketLcdAudio track={{ ...TRACK, title: "Morning Edition", artist: "Station", album: "", len: 0 }}
        state="playing" elapsed={754} volume={62} onSeek={onSeek} chrome={makeChrome()}/>,
    );
    const seek = getByTestId("plcd-seek");
    expect(seek).toHaveAttribute("aria-disabled", "true");
    fireEvent.pointerDown(seek, { clientX: 100, pointerId: 1 });
    fireEvent.pointerUp(seek, { clientX: 100, pointerId: 1 });
    expect(onSeek).not.toHaveBeenCalled();
    expect(getByText("12:34")).toBeInTheDocument();
    expect(lit(container, "LIVE")).toBe(true);
  });

  it("seeking a known-length track calls onSeek", () => {
    const onSeek = vi.fn();
    const { getByTestId } = render(
      <PocketLcdAudio track={TRACK} state="playing" elapsed={10} volume={50} onSeek={onSeek}/>,
    );
    const seek = getByTestId("plcd-seek");
    expect(seek).toHaveAttribute("aria-disabled", "false");
    fireEvent.pointerDown(seek, { clientX: 0, pointerId: 1 });
    fireEvent.pointerUp(seek, { clientX: 0, pointerId: 1 });
    expect(onSeek).toHaveBeenCalledWith(0);
  });

  it("long text renders, clamped in place", () => {
    const long = {
      ...TRACK,
      title: "The Ballad of the Long Distance Lorry Driver and His Dog Rex",
      artist: "The Extraordinarily Long Named Orchestra",
      album: "Songs From Somewhere Very Far Away Indeed",
    };
    const { getByTestId } = render(
      <PocketLcdAudio track={long} state="playing" elapsed={10} volume={50} chrome={makeChrome({ queueCount: 999 })}/>,
    );
    const title = getByTestId("plcd-title");
    expect(title.textContent).toBe(long.title);
    expect(title.style.webkitLineClamp).toBe("2");
    const artist = getByTestId("plcd-artist");
    expect(artist.textContent).toBe(long.artist);
    expect(artist.style.textOverflow).toBe("ellipsis");
  });

  it("missing art shows the dot-screen initial", () => {
    const { getByTestId } = render(
      <PocketLcdAudio track={{ ...TRACK, title: "Harvest Moon", album: "Harvest Moon" }} state="playing" elapsed={92} volume={50}/>,
    );
    expect(getByTestId("plcd-fallback-art").textContent).toBe("H");
  });
});
