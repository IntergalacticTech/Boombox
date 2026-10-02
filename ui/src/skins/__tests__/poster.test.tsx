// Poster skin (1c): Swiss concert poster, giant type on a red column.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import type { ChromeApi } from "../../lib/skinRegistry";
import { PosterAudio, POSTER_THEME, POSTER_SWATCH } from "../poster/Poster";
import type { Track } from "../../lib/types";

function makeChrome(over: Partial<ChromeApi> = {}): ChromeApi {
  return {
    sourceLabel: "LIBRARY",
    sourceColor: "#3FA7F5",
    sourceLive: false,
    queueCount: 3,
    skinName: "Poster",
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

describe("Poster skin", () => {
  it("exports a 9-slot theme and a 3-4 colour swatch", () => {
    for (const k of ["bg", "panel", "ink", "ink2", "accent", "accent2", "rule", "font", "mono"] as const) {
      expect(POSTER_THEME[k]).toBeTruthy();
    }
    expect(POSTER_SWATCH.length).toBeGreaterThanOrEqual(3);
    expect(POSTER_SWATCH.length).toBeLessThanOrEqual(4);
  });

  it("renders title, artist, album, source, queue count and skin name", () => {
    const { getByText, getByTestId } = render(
      <PosterAudio track={TRACK} state="playing" elapsed={67} volume={62} chrome={makeChrome({ queueCount: 999 })}/>,
    );
    expect(getByTestId("poster-title")).toHaveTextContent("Friends In Low Places");
    expect(getByText("Garth Brooks")).toBeInTheDocument();
    expect(getByText("No Fences")).toBeInTheDocument();
    expect(getByText("LIBRARY")).toBeInTheDocument();
    expect(getByText("999")).toBeInTheDocument();
    expect(getByText("Poster")).toBeInTheDocument();
    expect(getByText("VOL 62")).toBeInTheDocument();
    expect(getByText("1:07")).toBeInTheDocument();
    expect(getByText("4:19")).toBeInTheDocument();
  });

  it("play/pause calls onToggle and reflects the state in its name", () => {
    const onToggle = vi.fn();
    const { getByRole, rerender, queryByText } = render(
      <PosterAudio track={TRACK} state="playing" elapsed={0} volume={50} onToggle={onToggle}/>,
    );
    fireEvent.click(getByRole("button", { name: "Pause" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(queryByText("Paused")).toBeNull();
    rerender(<PosterAudio track={TRACK} state="paused" elapsed={0} volume={50} onToggle={onToggle}/>);
    fireEvent.click(getByRole("button", { name: "Play" }));
    expect(onToggle).toHaveBeenCalledTimes(2);
    expect(queryByText("Paused")).toBeInTheDocument();
  });

  it("paused cross-fades the black layer in with opacity only", () => {
    const { getByTestId, rerender } = render(
      <PosterAudio track={TRACK} state="playing" elapsed={0} volume={50}/>,
    );
    expect(getByTestId("poster-pause-layer").style.opacity).toBe("0");
    rerender(<PosterAudio track={TRACK} state="paused" elapsed={0} volume={50}/>);
    expect(getByTestId("poster-pause-layer").style.opacity).toBe("1");
  });

  it("prev / next / shuffle / repeat call their handlers", () => {
    const h = { onPrev: vi.fn(), onNext: vi.fn(), onToggleShuffle: vi.fn(), onToggleRepeat: vi.fn() };
    const { getByRole } = render(
      <PosterAudio track={TRACK} state="playing" elapsed={0} volume={50} shuffle repeat={false} {...h}/>,
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

  it("nav rows call Home, Library, Queue, Skin and Settings chrome actions", () => {
    const chrome = makeChrome();
    const { getByRole } = render(
      <PosterAudio track={TRACK} state="playing" elapsed={0} volume={50} chrome={chrome}/>,
    );
    fireEvent.click(getByRole("button", { name: "Home" }));
    fireEvent.click(getByRole("button", { name: "Library" }));
    fireEvent.click(getByRole("button", { name: /^Queue/ }));
    fireEvent.click(getByRole("button", { name: /^Skin/ }));
    fireEvent.click(getByRole("button", { name: "Settings" }));
    expect(chrome.onGoHome).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenQueue).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenSkinPicker).toHaveBeenCalledTimes(1);
    expect(chrome.onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it("idle (track null) renders without crashing and its Open Library tile opens the library", () => {
    const chrome = makeChrome({ sourceLabel: "IDLE", queueCount: 0 });
    const { getByText, getByRole, getByTestId } = render(
      <PosterAudio track={null} state="stopped" elapsed={0} volume={62} chrome={chrome}/>,
    );
    expect(getByTestId("poster-title")).toHaveTextContent("Nothing queued");
    expect(getByText("Open the Library to choose music")).toBeInTheDocument();
    fireEvent.click(getByRole("button", { name: "Open Library" }));
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
    expect(getByRole("slider", { name: "Seek" })).toHaveAttribute("aria-disabled", "true");
  });

  it("AUX with no track shows the line-in state", () => {
    const { getByText, getByTestId, queryByRole } = render(
      <PosterAudio track={null} state="stopped" elapsed={0} volume={null}
        chrome={makeChrome({ sourceLabel: "AUX", sourceLive: true })}/>,
    );
    expect(getByTestId("poster-title")).toHaveTextContent("Line-in");
    expect(getByText("AUX in")).toBeInTheDocument();
    expect(queryByRole("button", { name: "Open Library" })).toBeNull();
  });

  it("renders without chrome (skin-picker preview) and without nav actions", () => {
    const { getByRole, queryByText } = render(
      <PosterAudio track={TRACK} state="playing" elapsed={10} volume={50}/>,
    );
    expect(getByRole("button", { name: "Library" })).toBeDisabled();
    expect(getByRole("button", { name: "Home" })).toBeDisabled();
    expect(queryByText("LIBRARY")).toBeNull();
  });

  it("radio (len 0) disables seek and shows LIVE with the elapsed clock", () => {
    const onSeek = vi.fn();
    const radio: Track = { ...TRACK, title: "Morning Edition", artist: "KEXP 90.3", album: "", len: 0 };
    const { getByRole, getAllByText, getByText } = render(
      <PosterAudio track={radio} state="playing" elapsed={754} volume={62} chrome={makeChrome()} onSeek={onSeek}/>,
    );
    const slider = getByRole("slider", { name: "Seek" });
    expect(slider).toHaveAttribute("aria-disabled", "true");
    const bar = slider.querySelector("[data-progress]") as HTMLElement;
    fireEvent.pointerDown(bar, { clientX: 100, pointerId: 1 });
    fireEvent.pointerUp(bar, { clientX: 100, pointerId: 1 });
    expect(onSeek).not.toHaveBeenCalled();
    expect(getAllByText(/^live$/i).length).toBeGreaterThanOrEqual(2);
    expect(getByText("12:34")).toBeInTheDocument();
  });

  it("a seekable track enables seek", () => {
    const { getByRole } = render(
      <PosterAudio track={TRACK} state="playing" elapsed={67} volume={62} onSeek={vi.fn()}/>,
    );
    expect(getByRole("slider", { name: "Seek" })).toHaveAttribute("aria-disabled", "false");
  });

  it("missing art shows the two-tone initial block", () => {
    const { getByTestId } = render(
      <PosterAudio track={{ ...TRACK, title: "Harvest Moon", album: "Harvest Moon" }} state="playing" elapsed={0} volume={50}/>,
    );
    expect(getByTestId("poster-art-fallback")).toHaveTextContent("H");
  });

  it("long text renders, clamped rather than overflowing", () => {
    const long: Track = {
      ...TRACK,
      title: "The Ballad of the Long Distance Lorry Driver and His Dog Rex",
      artist: "The Extraordinarily Long Named Orchestra",
      album: "Songs From Somewhere Very Far Away Indeed",
    };
    const { getByTestId, getByText } = render(
      <PosterAudio track={long} state="playing" elapsed={0} volume={50} chrome={makeChrome({ queueCount: 999 })}/>,
    );
    const title = getByTestId("poster-title");
    expect(title).toHaveTextContent(long.title);
    expect(title.style.overflow).toBe("hidden");
    expect(getByText(long.artist).style.textOverflow).toBe("ellipsis");
    expect(getByText(long.album).style.textOverflow).toBe("ellipsis");
  });

  it("hides volume when it is unknown", () => {
    const { queryByText } = render(
      <PosterAudio track={TRACK} state="playing" elapsed={0} volume={null}/>,
    );
    expect(queryByText(/^VOL/)).toBeNull();
  });
  it("AirPlay (external, sourceLive) never shows LIVE or a fake clock", () => {
    const ext: Track = { ...TRACK, title: "Holocene", artist: "Bon Iver", album: "", len: 0 };
    const { queryByText, getByText, getByRole } = render(
      <PosterAudio track={ext} state="playing" elapsed={0} volume={null}
        chrome={makeChrome({ sourceLabel: "AIRPLAY", sourceLive: true })}/>,
    );
    expect(getByText("AIRPLAY")).toBeInTheDocument();
    expect(queryByText(/^live$/i)).toBeNull();
    expect(queryByText("0:00")).toBeNull();
    expect(getByRole("slider", { name: "Seek" })).toHaveAttribute("aria-disabled", "true");
  });

  it("uses track.artUrl directly without a lookup", () => {
    const fetchMock = vi.fn(() => new Promise(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(
      <PosterAudio track={{ ...TRACK, artUrl: "/art/direct.jpg" }} state="playing" elapsed={0} volume={50}/>,
    );
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/art/direct.jpg");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("falls back to the shared album-art lookup when artUrl is missing", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ url: "/art/looked-up.jpg" }),
    })));
    const t: Track = { ...TRACK, uri: "local:track:lookup", artist: "Lookup Artist", album: "Lookup Album" };
    const { container } = render(<PosterAudio track={t} state="playing" elapsed={0} volume={50}/>);
    await waitFor(() => {
      expect(container.querySelector("img")?.getAttribute("src")).toBe("/art/looked-up.jpg");
    });
  });

  it("tracks queued but none loaded shows a ready state with Play enabled", () => {
    const onToggle = vi.fn();
    const chrome = makeChrome({ sourceLabel: "LIBRARY", sourceLive: false, queueCount: 10 });
    const { getByRole, container, rerender } = render(
      <PosterAudio track={null} state="paused" elapsed={0} volume={50} chrome={chrome} onToggle={onToggle}/>,
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

    rerender(<PosterAudio track={null} state="paused" elapsed={0} volume={50}
      chrome={makeChrome({ sourceLabel: "LIBRARY", sourceLive: false, queueCount: 1 })} onToggle={onToggle}/>);
    expect(container.textContent).toMatch(/1 track queued/i);
  });
});
