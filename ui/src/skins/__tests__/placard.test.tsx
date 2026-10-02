// Placard skin (1b): gallery wall, cover as the work and the track as its label.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import type { ChromeApi } from "../../lib/skinRegistry";
import { PlacardAudio, PLACARD_THEME, PLACARD_SWATCH } from "../placard/Placard";
import type { Track } from "../../lib/types";

function makeChrome(over: Partial<ChromeApi> = {}): ChromeApi {
  return {
    sourceLabel: "LIBRARY",
    sourceColor: "#3FA7F5",
    sourceLive: false,
    queueCount: 10,
    skinName: "Placard",
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
  // Art lookup hits /api/art; keep it pending under jsdom.
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("Placard skin", () => {
  it("exports a 9-slot theme and a swatch", () => {
    expect(Object.keys(PLACARD_THEME).sort()).toEqual(
      ["accent", "accent2", "bg", "font", "ink", "ink2", "mono", "panel", "rule"]);
    expect(PLACARD_SWATCH.length).toBeGreaterThanOrEqual(3);
    expect(PLACARD_SWATCH.length).toBeLessThanOrEqual(4);
  });

  it("renders title, artist, album, times and volume", () => {
    const { getByText, container } = render(
      <PlacardAudio track={TRACK} state="playing" elapsed={67} volume={62} chrome={makeChrome()}/>,
    );
    expect(getByText("Friends In Low Places")).toBeInTheDocument();
    expect(getByText("Garth Brooks")).toBeInTheDocument();
    expect(getByText("No Fences")).toBeInTheDocument();
    const text = container.textContent ?? "";
    expect(text).toContain("1:07");
    expect(text).toContain("4:19");
    expect(text).toContain("VOL 62");
    expect(text).not.toContain("Paused");
  });

  it("play/pause calls onToggle and reflects the state", () => {
    const onToggle = vi.fn();
    const { getByRole, rerender } = render(
      <PlacardAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={makeChrome()} onToggle={onToggle}/>,
    );
    fireEvent.click(getByRole("button", { name: "Pause" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(<PlacardAudio track={TRACK} state="paused" elapsed={10} volume={50} chrome={makeChrome()} onToggle={onToggle}/>);
    fireEvent.click(getByRole("button", { name: "Play" }));
    expect(onToggle).toHaveBeenCalledTimes(2);
  });

  it("paused shows the oxblood Paused line and dims the artwork", () => {
    const { getByText, getByTestId } = render(
      <PlacardAudio track={TRACK} state="paused" elapsed={10} volume={50} chrome={makeChrome()}/>,
    );
    expect(getByText("Paused")).toBeInTheDocument();
    expect(getByTestId("placard-art").style.opacity).toBe("0.4");
  });

  it("prev/next/shuffle/repeat call their handlers", () => {
    const h = { onPrev: vi.fn(), onNext: vi.fn(), onToggleShuffle: vi.fn(), onToggleRepeat: vi.fn() };
    const { getByRole } = render(
      <PlacardAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={makeChrome()}
        shuffle repeat {...h}/>,
    );
    fireEvent.click(getByRole("button", { name: "Previous" }));
    fireEvent.click(getByRole("button", { name: "Next" }));
    fireEvent.click(getByRole("button", { name: "Shuffle" }));
    fireEvent.click(getByRole("button", { name: "Repeat" }));
    expect(h.onPrev).toHaveBeenCalledTimes(1);
    expect(h.onNext).toHaveBeenCalledTimes(1);
    expect(h.onToggleShuffle).toHaveBeenCalledTimes(1);
    expect(h.onToggleRepeat).toHaveBeenCalledTimes(1);
    expect(getByRole("button", { name: "Shuffle" })).toHaveAttribute("aria-pressed", "true");
    expect(getByRole("button", { name: "Repeat" })).toHaveAttribute("aria-pressed", "true");
  });

  it("navigation rail calls every chrome action and shows queue + skin name", () => {
    const chrome = makeChrome({ queueCount: 999, skinName: "Placard" });
    const { getByRole } = render(
      <PlacardAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={chrome}/>,
    );
    fireEvent.click(getByRole("button", { name: "Home" }));
    fireEvent.click(getByRole("button", { name: "Library" }));
    fireEvent.click(getByRole("button", { name: "Queue" }));
    fireEvent.click(getByRole("button", { name: "Skin" }));
    fireEvent.click(getByRole("button", { name: "Settings" }));
    expect(chrome.onGoHome).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenQueue).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenSkinPicker).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenSettings).toHaveBeenCalledTimes(1);
    expect(getByRole("button", { name: "Queue" }).textContent).toContain("999");
    expect(getByRole("button", { name: "Skin" }).textContent).toContain("Placard");
    expect(getByRole("button", { name: "Home" }).textContent).toContain("LIBRARY");
  });

  it("idle (track null) renders the empty frame, and it opens the Library", () => {
    const chrome = makeChrome({ sourceLabel: "IDLE", queueCount: 0 });
    const { getAllByText, getByText, getByRole, queryByText } = render(
      <PlacardAudio track={null} state="stopped" elapsed={0} volume={50} chrome={chrome}/>,
    );
    expect(getAllByText("Nothing queued").length).toBeGreaterThan(0);
    expect(getByText("Open the Library to choose music")).toBeInTheDocument();
    expect(queryByText("Paused")).toBeNull();
    fireEvent.click(getByRole("button", { name: /open library/i }));
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
  });

  it("AUX with no track reads as line-in", () => {
    const { getByText, container } = render(
      <PlacardAudio track={null} state="playing" elapsed={0} volume={null}
        chrome={makeChrome({ sourceLabel: "AUX", sourceLive: true, queueCount: 0 })}/>,
    );
    expect(getByText("Line-in")).toBeInTheDocument();
    expect(getByText("AUX in")).toBeInTheDocument();
    expect(container.textContent).not.toContain("VOL");
  });

  it("external source (AirPlay) omits album, times, volume and the LIVE tag", () => {
    const t: Track = { uri: "airplay:1", title: "Holocene", artist: "Bon Iver", album: "", time: "", len: 0, hue: 200 };
    const { container } = render(
      <PlacardAudio track={t} state="playing" elapsed={0} volume={null}
        chrome={makeChrome({ sourceLabel: "AIRPLAY", sourceLive: true, queueCount: 0 })}/>,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Holocene");
    expect(text).toContain("AIRPLAY");
    expect(text).not.toContain("LIVE");
    expect(text).not.toContain("VOL");
    expect(text).not.toContain("0:00");
  });

  it("radio (len 0) is LIVE, counts up and disables seek", () => {
    const onSeek = vi.fn();
    const radio: Track = { uri: "stream:1", title: "Morning Edition", artist: "KEXP 90.3", album: "", time: "", len: 0, hue: 205 };
    const { getByTestId, container } = render(
      <PlacardAudio track={radio} state="playing" elapsed={754} volume={62} chrome={makeChrome()} onSeek={onSeek}/>,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("LIVE");
    expect(text).toContain("12:34");
    const seek = getByTestId("placard-seek");
    expect(seek).toHaveAttribute("aria-disabled", "true");
    const bar = seek.firstElementChild as HTMLElement;
    fireEvent.pointerDown(bar, { clientX: 10, pointerId: 1 });
    fireEvent.pointerUp(bar, { clientX: 10, pointerId: 1 });
    expect(onSeek).not.toHaveBeenCalled();
  });

  it("seeking a normal track calls onSeek", () => {
    const onSeek = vi.fn();
    const { getByTestId } = render(
      <PlacardAudio track={TRACK} state="playing" elapsed={10} volume={62} chrome={makeChrome()} onSeek={onSeek}/>,
    );
    const seek = getByTestId("placard-seek");
    expect(seek).not.toHaveAttribute("aria-disabled");
    const bar = seek.firstElementChild as HTMLElement;
    fireEvent.pointerDown(bar, { clientX: 0, pointerId: 1 });
    fireEvent.pointerUp(bar, { clientX: 0, pointerId: 1 });
    expect(onSeek).toHaveBeenCalledTimes(1);
  });

  it("long text renders, with the title clamped", () => {
    const long: Track = {
      ...TRACK,
      title: "The Ballad of the Long Distance Lorry Driver and His Dog Rex",
      artist: "The Extraordinarily Long Named Orchestra",
      album: "Songs From Somewhere Very Far Away Indeed",
    };
    const { getByText, getByTestId } = render(
      <PlacardAudio track={long} state="playing" elapsed={10} volume={62} chrome={makeChrome({ queueCount: 999 })}/>,
    );
    expect(getByText(long.artist)).toBeInTheDocument();
    expect(getByText(long.album)).toBeInTheDocument();
    const title = getByTestId("placard-title");
    expect(title.textContent).toBe(long.title);
    expect(title.style.overflow).toBe("hidden");
  });

  it("missing art shows the tinted mat with the album initial", () => {
    const t: Track = { ...TRACK, title: "Harvest Moon", artist: "Neil Young", album: "Harvest Moon" };
    const { getByTestId } = render(
      <PlacardAudio track={t} state="playing" elapsed={92} volume={62} chrome={makeChrome()}/>,
    );
    expect(getByTestId("placard-missing-art").textContent).toBe("H");
  });

  it("renders without chrome and without handlers (skin-picker preview)", () => {
    const { getByText, getByRole } = render(
      <PlacardAudio track={TRACK} state="playing" elapsed={10} volume={50}/>,
    );
    expect(getByText("Friends In Low Places")).toBeInTheDocument();
    expect(getByRole("button", { name: "Library" })).toBeDisabled();
    expect(() => fireEvent.click(getByRole("button", { name: "Pause" }))).not.toThrow();
  });

  it("renders idle without chrome", () => {
    const { getAllByText } = render(<PlacardAudio track={null} state="stopped" elapsed={0} volume={null}/>);
    expect(getAllByText("Nothing queued").length).toBeGreaterThan(0);
  });
});
