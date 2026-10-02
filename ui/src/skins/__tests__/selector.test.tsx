// Selector skin: jukebox title strip, 45 rpm label and push buttons.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import type { ChromeApi } from "../../lib/skinRegistry";
import { SelectorAudio } from "../selector/Selector";
import type { Track } from "../../lib/types";

function makeChrome(over: Partial<ChromeApi> = {}): ChromeApi {
  return {
    sourceLabel: "LIBRARY",
    sourceColor: "#3FA7F5",
    sourceLive: false,
    queueCount: 10,
    skinName: "Selector",
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
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("Selector skin", () => {
  it("renders title, artist, album, times and volume", () => {
    const { getByText, getByTestId } = render(
      <SelectorAudio track={TRACK} state="playing" elapsed={67} volume={62} chrome={makeChrome()}/>,
    );
    expect(getByTestId("selector-title")).toHaveTextContent("Friends In Low Places");
    expect(getByTestId("selector-artist")).toHaveTextContent("Garth Brooks");
    expect(getByText("No Fences")).toBeInTheDocument();
    expect(getByText("1:07")).toBeInTheDocument();
    expect(getByText("4:19")).toBeInTheDocument();
    expect(getByText("VOL 62")).toBeInTheDocument();
  });

  it("transport keys call their handlers", () => {
    const h = { onToggle: vi.fn(), onPrev: vi.fn(), onNext: vi.fn(), onToggleShuffle: vi.fn(), onToggleRepeat: vi.fn() };
    const { getByRole } = render(
      <SelectorAudio track={TRACK} state="playing" elapsed={0} volume={50} chrome={makeChrome()} {...h}/>,
    );
    fireEvent.click(getByRole("button", { name: "Pause" }));
    fireEvent.click(getByRole("button", { name: "Previous" }));
    fireEvent.click(getByRole("button", { name: "Next" }));
    fireEvent.click(getByRole("button", { name: "Shuffle" }));
    fireEvent.click(getByRole("button", { name: "Repeat" }));
    for (const fn of Object.values(h)) expect(fn).toHaveBeenCalledTimes(1);
  });

  it("paused shows Play and the PAUSED stamp; Play calls onToggle", () => {
    const onToggle = vi.fn();
    const { getByRole, getByText } = render(
      <SelectorAudio track={TRACK} state="paused" elapsed={0} volume={50} chrome={makeChrome()} onToggle={onToggle}/>,
    );
    expect(getByText("PAUSED")).toBeInTheDocument();
    fireEvent.click(getByRole("button", { name: "Play" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("shuffle and repeat expose their on state", () => {
    const { getByRole } = render(
      <SelectorAudio track={TRACK} state="playing" elapsed={0} volume={50} shuffle repeat
        onToggleShuffle={() => {}} onToggleRepeat={() => {}}/>,
    );
    expect(getByRole("button", { name: "Shuffle" })).toHaveAttribute("aria-pressed", "true");
    expect(getByRole("button", { name: "Repeat" })).toHaveAttribute("aria-pressed", "true");
  });

  it("nav row calls every chrome action and shows queue count and skin name", () => {
    const chrome = makeChrome({ queueCount: 999 });
    const { getByRole } = render(
      <SelectorAudio track={TRACK} state="playing" elapsed={0} volume={50} chrome={chrome}/>,
    );
    const pairs: [string, keyof ChromeApi][] = [
      ["Home", "onGoHome"], ["Library", "onOpenLibrary"], ["Queue", "onOpenQueue"],
      ["Skin", "onOpenSkinPicker"], ["Settings", "onOpenSettings"],
    ];
    for (const [name, fn] of pairs) {
      fireEvent.click(getByRole("button", { name }));
      expect(chrome[fn]).toHaveBeenCalledTimes(1);
    }
    expect(getByRole("button", { name: "Queue" })).toHaveTextContent("QUEUE999");
    expect(getByRole("button", { name: "Skin" })).toHaveTextContent("Selector");
    expect(getByRole("button", { name: "Home" })).toHaveTextContent("HOME · LIBRARY");
  });

  it("idle (track=null) shows the empty strip, disables transport and highlights Library", () => {
    const chrome = makeChrome({ sourceLabel: "IDLE", queueCount: 0 });
    const { getByTestId, getByRole, queryByText } = render(
      <SelectorAudio track={null} state="stopped" elapsed={0} volume={50} chrome={chrome}/>,
    );
    expect(getByTestId("selector-title")).toHaveTextContent("Nothing queued");
    expect(getByTestId("selector-artist")).toHaveTextContent("Open the Library to choose music");
    expect(getByRole("button", { name: "Play" })).toBeDisabled();
    expect(getByRole("button", { name: "Next" })).toBeDisabled();
    expect(queryByText("PAUSED")).toBeNull();
    fireEvent.click(getByRole("button", { name: "Library" }));
    expect(chrome.onOpenLibrary).toHaveBeenCalled();
  });

  it("AUX with no track shows the line-in strip", () => {
    const { getByTestId } = render(
      <SelectorAudio track={null} state="stopped" elapsed={0} volume={null}
        chrome={makeChrome({ sourceLabel: "AUX", sourceLive: true })}/>,
    );
    expect(getByTestId("selector-title")).toHaveTextContent("Line-in");
    expect(getByTestId("selector-artist")).toHaveTextContent("Playing from the AUX jack");
  });

  it("chrome undefined renders without nav actions or source", () => {
    const { getByRole, queryByTestId } = render(
      <SelectorAudio track={TRACK} state="playing" elapsed={10} volume={50}/>,
    );
    expect(queryByTestId("selector-source")).toBeNull();
    expect(getByRole("button", { name: "Settings" })).toBeDisabled();
  });

  it("radio (len 0) disables seek, counts elapsed and shows LIVE", () => {
    const onSeek = vi.fn();
    const radio: Track = { ...TRACK, title: "Morning Edition", artist: "KEXP 90.3", album: "", len: 0 };
    const { getByRole, getByTestId, getAllByText } = render(
      <SelectorAudio track={radio} state="playing" elapsed={754} volume={50} chrome={makeChrome()} onSeek={onSeek}/>,
    );
    const slider = getByRole("slider", { name: "Seek" });
    expect(slider).toHaveAttribute("aria-disabled", "true");
    fireEvent.pointerDown(slider.firstElementChild as Element, { clientX: 100 });
    fireEvent.pointerUp(slider.firstElementChild as Element, { clientX: 100 });
    expect(onSeek).not.toHaveBeenCalled();
    expect(getByTestId("selector-elapsed")).toHaveTextContent("12:34");
    expect(getAllByText("LIVE").length).toBeGreaterThanOrEqual(1);
  });

  it("external AirPlay shows no times and no volume", () => {
    const t: Track = { ...TRACK, album: "", len: 0 };
    const { getByTestId, queryByText } = render(
      <SelectorAudio track={t} state="playing" elapsed={0} volume={null}
        chrome={makeChrome({ sourceLabel: "AIRPLAY", sourceLive: true })}/>,
    );
    expect(getByTestId("selector-elapsed")).toHaveTextContent("");
    expect(queryByText(/^VOL/)).toBeNull();
    expect(getByTestId("selector-source")).toHaveTextContent("AIRPLAY");
    expect(queryByText("LIVE")).toBeNull();
  });

  it.each(["AIRPLAY", "SPOTIFY", "BLUETOOTH", "AUX"])("%s never shows LIVE", (sourceLabel) => {
    const t: Track = { ...TRACK, album: "", len: 0 };
    const { container } = render(
      <SelectorAudio track={sourceLabel === "AUX" ? null : t} state="playing" elapsed={30} volume={null}
        chrome={makeChrome({ sourceLabel, sourceLive: true })}/>,
    );
    expect(container.textContent).not.toMatch(/LIVE/);
  });

  it("radio without chrome still shows LIVE", () => {
    const { getAllByText } = render(
      <SelectorAudio track={{ ...TRACK, len: 0 }} state="playing" elapsed={5} volume={50}/>,
    );
    expect(getAllByText("LIVE").length).toBeGreaterThanOrEqual(1);
  });

  it("uses track.artUrl when present", () => {
    const { container, queryByTestId } = render(
      <SelectorAudio track={{ ...TRACK, artUrl: "/art/x.jpg" }} state="playing" elapsed={0} volume={50}/>,
    );
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/art/x.jpg");
    expect(queryByTestId("selector-fallback-label")).toBeNull();
  });

  it("falls back to the shared album-art lookup when artUrl is missing", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ url: "/looked-up.jpg" }) })));
    const t: Track = { ...TRACK, uri: "u:lookup", artist: "Lookup Artist", album: "Lookup Album" };
    const { container } = render(
      <SelectorAudio track={t} state="playing" elapsed={0} volume={50}/>,
    );
    await waitFor(() => expect(container.querySelector("img")?.getAttribute("src")).toBe("/looked-up.jpg"));
  });

  it("long text renders (clamped/ellipsised by CSS)", () => {
    const long: Track = {
      ...TRACK,
      title: "The Ballad of the Long Distance Lorry Driver and His Dog Rex",
      artist: "The Extraordinarily Long Named Orchestra",
      album: "Songs From Somewhere Very Far Away Indeed",
    };
    const { getByTestId, getByText } = render(
      <SelectorAudio track={long} state="playing" elapsed={0} volume={50} chrome={makeChrome({ queueCount: 999 })}/>,
    );
    expect(getByTestId("selector-title")).toHaveTextContent(long.title);
    expect(getByTestId("selector-artist")).toHaveTextContent(long.artist);
    expect(getByText(long.album)).toBeInTheDocument();
  });

  it("missing art shows the coloured 45 label with the initial", () => {
    const t: Track = { ...TRACK, title: "Harvest Moon", artist: "Neil Young", album: "Harvest Moon" };
    const { getByTestId } = render(
      <SelectorAudio track={t} state="playing" elapsed={0} volume={50}/>,
    );
    expect(getByTestId("selector-fallback-label")).toHaveTextContent("H");
  });

  it("tracks queued but none loaded shows a ready state with Play enabled", () => {
    const onToggle = vi.fn();
    const chrome = makeChrome({ sourceLabel: "LIBRARY", sourceLive: false, queueCount: 10 });
    const { getByRole, container, rerender } = render(
      <SelectorAudio track={null} state="paused" elapsed={0} volume={50} chrome={chrome} onToggle={onToggle}/>,
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

    rerender(<SelectorAudio track={null} state="paused" elapsed={0} volume={50}
      chrome={makeChrome({ sourceLabel: "LIBRARY", sourceLive: false, queueCount: 1 })} onToggle={onToggle}/>);
    expect(container.textContent).toMatch(/1 track queued/i);
  });
});
