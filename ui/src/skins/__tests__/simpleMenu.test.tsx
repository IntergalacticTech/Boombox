// Simple skin: the left nav menu is hidden by default and slides in from a
// fixed upper-left Menu button (touch-only kiosk, no hover).
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act, within } from "@testing-library/react";
import type { ChromeApi } from "../../lib/skinRegistry";
import { SimpleAudio } from "../simple/Simple";
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
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  vi.stubGlobal("WebSocket", class {
    static OPEN = 1; static CONNECTING = 0;
    readyState = 0;
    close() {}
  });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

function setup(chrome = makeChrome()) {
  const utils = render(
    <SimpleAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={chrome}/>,
  );
  const menuBtn = () => utils.getByRole("button", { name: "Menu" });
  const nav = () => utils.container.querySelector("nav#simple-nav") as HTMLElement;
  const isOpen = () => menuBtn().getAttribute("aria-expanded") === "true";
  return { ...utils, chrome, menuBtn, nav, isOpen };
}

describe("Simple skin slide-out menu", () => {
  it("starts closed: nav items are hidden, inert and not reachable by role", () => {
    const { isOpen, nav, queryByRole, queryAllByRole, menuBtn } = setup();
    expect(isOpen()).toBe(false);
    expect(menuBtn()).toHaveAttribute("aria-controls", "simple-nav");
    expect(nav()).toHaveAttribute("aria-hidden", "true");
    expect(nav().hasAttribute("inert")).toBe(true);
    expect(queryByRole("navigation", { name: "Main menu" })).toBeNull();
    for (const name of ["Now Playing", "Home", "Library", "Settings"]) {
      expect(queryAllByRole("button", { name })).toHaveLength(0);
    }
    // The slide-out is transform-only.
    expect(nav().style.transform).toBe("translateX(-100%)");
  });

  it("the Menu button opens the menu, and tapping it again closes it", () => {
    const { menuBtn, isOpen, nav, getByRole } = setup();
    fireEvent.click(menuBtn());
    expect(isOpen()).toBe(true);
    expect(nav()).not.toHaveAttribute("aria-hidden", "true");
    expect(nav().hasAttribute("inert")).toBe(false);
    expect(nav().style.transform).toBe("translateX(0)");
    const menu = within(getByRole("navigation", { name: "Main menu" }));
    expect(menu.getByRole("button", { name: "Settings" })).toBeInTheDocument();
    fireEvent.click(menuBtn());
    expect(isOpen()).toBe(false);
  });

  it("choosing a nav item runs its action and closes the menu", () => {
    const { menuBtn, isOpen, getByRole, chrome } = setup();
    fireEvent.click(menuBtn());
    fireEvent.click(getByRole("button", { name: "Settings" }));
    expect(chrome.onOpenSettings).toHaveBeenCalledTimes(1);
    expect(isOpen()).toBe(false);

    fireEvent.click(menuBtn());
    fireEvent.click(getByRole("button", { name: "Home" }));
    expect(chrome.onGoHome).toHaveBeenCalledTimes(1);
    expect(isOpen()).toBe(false);

    // "Now Playing" is the current view: it just closes the menu.
    fireEvent.click(menuBtn());
    fireEvent.click(getByRole("button", { name: "Now Playing" }));
    expect(isOpen()).toBe(false);
  });

  it("tapping the scrim closes the menu", () => {
    const { menuBtn, isOpen, getByTestId, chrome } = setup();
    fireEvent.click(menuBtn());
    expect(isOpen()).toBe(true);
    fireEvent.click(getByTestId("simple-menu-scrim"));
    expect(isOpen()).toBe(false);
    expect(chrome.onOpenLibrary).not.toHaveBeenCalled();
  });

  it("auto-closes after 8 s with no touches inside it", () => {
    vi.useFakeTimers();
    const { menuBtn, isOpen, nav } = setup();
    fireEvent.click(menuBtn());
    act(() => { vi.advanceTimersByTime(7000); });
    expect(isOpen()).toBe(true);
    // A touch inside the menu restarts the countdown.
    fireEvent.pointerDown(nav());
    act(() => { vi.advanceTimersByTime(7000); });
    expect(isOpen()).toBe(true);
    act(() => { vi.advanceTimersByTime(1100); });
    expect(isOpen()).toBe(false);
  });

  it("schedules no timers while closed", () => {
    vi.useFakeTimers();
    const { menuBtn } = setup();
    const before = vi.getTimerCount();
    fireEvent.click(menuBtn());
    expect(vi.getTimerCount()).toBe(before + 1);
    fireEvent.click(menuBtn());
    expect(vi.getTimerCount()).toBe(before);
  });

  it("player content keeps the Library shortcut while the menu is closed", () => {
    const { getByRole, chrome } = setup(makeChrome({ queueCount: 0 }));
    fireEvent.click(getByRole("button", { name: /browse library/i }));
    expect(chrome.onOpenLibrary).toHaveBeenCalledTimes(1);
  });
});
