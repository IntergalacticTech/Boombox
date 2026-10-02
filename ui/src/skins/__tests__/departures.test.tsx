// Departures skin (split-flap board): rendering, controls, chrome wiring,
// and the edge states from the design (idle, AUX, radio, long text).
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import type { ChromeApi } from "../../lib/skinRegistry";
import { DeparturesAudio, DEPARTURES_THEME, DEPARTURES_SWATCH } from "../departures/Departures";
import type { Track } from "../../lib/types";

function makeChrome(over: Partial<ChromeApi> = {}): ChromeApi {
  return {
    sourceLabel: "LIBRARY",
    sourceColor: "#3FA7F5",
    sourceLive: false,
    queueCount: 10,
    skinName: "Departures",
    onGoHome: vi.fn(),
    onOpenQueue: vi.fn(),
    onOpenLibrary: vi.fn(),
    onOpenSkinPicker: vi.fn(),
    onOpenSettings: vi.fn(),
    ...over,
  };
}

const TRACK: Track = {
  uri: "local:track:1", artist: "Garth Brooks", title: "Friends In Low Places",
  album: "No Fences", time: "4:19", len: 259, hue: 28,
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

describe("Departures skin", () => {
  it("exports a 9-slot theme and a swatch", () => {
    expect(Object.keys(DEPARTURES_THEME)).toHaveLength(9);
    expect(DEPARTURES_SWATCH.length).toBeGreaterThanOrEqual(3);
  });

  it("renders title, artist, album, source and time", () => {
    const { getByText, container } = render(
      <DeparturesAudio track={TRACK} state="playing" elapsed={67} volume={62} chrome={makeChrome()}/>,
    );
    expect(getByText("Friends In Low Places")).toBeInTheDocument();
    expect(getByText("Garth Brooks")).toBeInTheDocument();
    expect(getByText("No Fences")).toBeInTheDocument();
    const text = container.textContent ?? "";
    expect(text).toContain("LIBRARY");
    expect(text).toContain("1:07");
    expect(text).toContain("4:19");
    expect(text).toContain("VOL 62");
    expect(text).toContain("PLAYING");
  });

  it("play/pause calls onToggle and reflects the state", () => {
    const onToggle = vi.fn();
    const { getByRole, rerender, container } = render(
      <DeparturesAudio track={TRACK} state="playing" elapsed={10} volume={50} onToggle={onToggle}/>,
    );
    fireEvent.click(getByRole("button", { name: "Pause" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(<DeparturesAudio track={TRACK} state="paused" elapsed={10} volume={50} onToggle={onToggle}/>);
    fireEvent.click(getByRole("button", { name: "Play" }));
    expect(onToggle).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("PAUSED");
  });

  it("prev / next / shuffle / repeat call their handlers", () => {
    const h = { onPrev: vi.fn(), onNext: vi.fn(), onToggleShuffle: vi.fn(), onToggleRepeat: vi.fn() };
    const { getByRole } = render(
      <DeparturesAudio track={TRACK} state="playing" elapsed={10} volume={50} shuffle repeat={false} {...h}/>,
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
    expect(getByRole("button", { name: "Repeat" })).toHaveAttribute("aria-pressed", "false");
  });

  it("Library entry calls chrome.onOpenLibrary", () => {
    const chrome = makeChrome();
    const { getByRole } = render(
      <DeparturesAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={chrome}/>,
    );
    fireEvent.click(getByRole("button", { name: "Library" }));
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenQueue).not.toHaveBeenCalled();
  });

  it("Home, Queue, Skin and Settings call their chrome actions", () => {
    const chrome = makeChrome({ queueCount: 999 });
    const { getByRole, container } = render(
      <DeparturesAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={chrome}/>,
    );
    fireEvent.click(getByRole("button", { name: "Home" }));
    fireEvent.click(getByRole("button", { name: /^Queue/ }));
    fireEvent.click(getByRole("button", { name: /^Skin/ }));
    fireEvent.click(getByRole("button", { name: "Settings" }));
    expect(chrome.onGoHome).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenQueue).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenSkinPicker).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenSettings).toHaveBeenCalledTimes(1);
    const text = container.textContent ?? "";
    expect(text).toContain("999");
    expect(text).toContain("HOME · LIBRARY");
    expect(text).toContain("DEPARTURES");
  });

  it("renders the idle state (track null) with an Open Library tile", () => {
    const chrome = makeChrome({ sourceLabel: "IDLE", queueCount: 0 });
    const { getByRole, container } = render(
      <DeparturesAudio track={null} state="stopped" elapsed={0} volume={50} chrome={chrome}/>,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Nothing queued");
    expect(text).toContain("IDLE");
    expect(getByRole("button", { name: "Play" })).toBeDisabled();
    fireEvent.click(getByRole("button", { name: "Open Library" }));
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
  });

  it("renders the AUX line-in state", () => {
    const { container, queryByText } = render(
      <DeparturesAudio track={null} state="stopped" elapsed={0} volume={null}
        chrome={makeChrome({ sourceLabel: "AUX", sourceLive: true, queueCount: 0 })}/>,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Line-in");
    expect(text).toContain("LINE-IN");
    expect(text).toContain("AUX in");
    expect(queryByText(/VOL/)).toBeNull();
  });

  it("renders without chrome and without crashing", () => {
    const { getByRole, getByText } = render(
      <DeparturesAudio track={TRACK} state="playing" elapsed={10} volume={50}/>,
    );
    expect(getByText("Friends In Low Places")).toBeInTheDocument();
    expect(getByRole("button", { name: "Library" })).toBeDisabled();
    render(<DeparturesAudio track={null} state="stopped" elapsed={0} volume={null}/>);
  });

  it("radio (len 0) disables seek and shows LIVE with elapsed counting up", () => {
    const onSeek = vi.fn();
    const radio: Track = { ...TRACK, title: "Morning Edition", artist: "KEXP 90.3", album: "", len: 0, time: "", hue: 205 };
    const { getByRole, container } = render(
      <DeparturesAudio track={radio} state="playing" elapsed={754} volume={62} chrome={makeChrome()} onSeek={onSeek}/>,
    );
    const slider = getByRole("slider", { name: "Seek" });
    expect(slider).toHaveAttribute("aria-disabled", "true");
    fireEvent.pointerDown(slider.firstElementChild!, { clientX: 100, pointerId: 1 });
    fireEvent.pointerUp(slider.firstElementChild!, { clientX: 100, pointerId: 1 });
    expect(onSeek).not.toHaveBeenCalled();
    const text = container.textContent ?? "";
    expect(text).toContain("LIVE");
    expect(text).toContain("12:34");
  });

  it("timed tracks have an enabled seek bar", () => {
    const { getByRole } = render(
      <DeparturesAudio track={TRACK} state="playing" elapsed={67} volume={62} onSeek={vi.fn()}/>,
    );
    expect(getByRole("slider", { name: "Seek" })).toHaveAttribute("aria-disabled", "false");
  });

  it("external AirPlay source hides album, length and volume", () => {
    const ext: Track = { ...TRACK, title: "Holocene", artist: "Bon Iver", album: "", len: 0, time: "" };
    const { container } = render(
      <DeparturesAudio track={ext} state="playing" elapsed={0} volume={null}
        chrome={makeChrome({ sourceLabel: "AIRPLAY", sourceLive: true, queueCount: 0 })}/>,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Holocene");
    expect(text).toContain("AIRPLAY");
    expect(text).not.toContain("VOL");
    expect(text).not.toContain("0:00");
    expect(text).not.toContain("LIVE");
  });

  it.each(["AIRPLAY", "SPOTIFY", "BLUETOOTH"])("%s never shows LIVE, even with a length-less track", (src) => {
    const ext: Track = { ...TRACK, album: "", len: 0, time: "" };
    const { container } = render(
      <DeparturesAudio track={ext} state="playing" elapsed={42} volume={50}
        chrome={makeChrome({ sourceLabel: src, sourceLive: true })}/>,
    );
    expect(container.textContent).not.toContain("LIVE");
  });

  it("flips flaps only when a value changes while playing", () => {
    const next: Track = { ...TRACK, uri: "local:track:2", title: "The Dance" };
    const { container, rerender } = render(
      <DeparturesAudio track={TRACK} state="paused" elapsed={10} volume={50}/>,
    );
    expect(container.querySelector(".dep-flip")).toBeNull();
    rerender(<DeparturesAudio track={next} state="paused" elapsed={10} volume={50}/>);
    expect(container.querySelector(".dep-flip")).toBeNull();
    rerender(<DeparturesAudio track={TRACK} state="playing" elapsed={10} volume={50}/>);
    expect(container.querySelector(".dep-flip")).not.toBeNull();
  });

  it("renders long text without dropping it", () => {
    const long: Track = {
      ...TRACK,
      title: "The Ballad of the Long Distance Lorry Driver and His Dog Rex",
      artist: "The Extraordinarily Long Named Orchestra",
      album: "Songs From Somewhere Very Far Away Indeed",
    };
    const { getByText } = render(
      <DeparturesAudio track={long} state="playing" elapsed={10} volume={50} chrome={makeChrome({ queueCount: 999 })}/>,
    );
    expect(getByText(long.title)).toBeInTheDocument();
    expect(getByText(long.artist)).toBeInTheDocument();
    expect(getByText(long.album)).toBeInTheDocument();
  });

  it("missing art shows the split-flap initial tile", () => {
    const noart: Track = { ...TRACK, title: "Harvest Moon", artist: "Neil Young", album: "Harvest Moon", hue: 32 };
    const { getByTestId } = render(
      <DeparturesAudio track={noart} state="playing" elapsed={92} volume={50}/>,
    );
    expect(getByTestId("departures-art-fallback").textContent).toBe("H");
  });
});
