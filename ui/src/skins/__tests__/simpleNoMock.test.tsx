// The Simple skin used to ship design-mock values (fake queue, fake DAC /
// Wi-Fi / format chips, a blinking fake UTC clock). Keep them out.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
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

describe("Simple skin shows no design-mock data", () => {
  it("never renders the demo queue or fake hardware stats", () => {
    const { container } = render(
      <SimpleAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={makeChrome({ queueCount: 0 })}/>,
    );
    const text = container.textContent ?? "";
    for (const fake of ["DEMO", "Khruangbin", "pcm5122", "dBm", "MP3 320", "23:41", "UTC", "48k/24b", "[ CPU ]"]) {
      expect(text).not.toContain(fake);
    }
    expect(text).toContain("Nothing queued");
  });

  it("summarises a non-empty queue and opens it on tap", () => {
    const chrome = makeChrome({ queueCount: 10 });
    const { getByText, getByRole } = render(
      <SimpleAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={chrome}/>,
    );
    expect(getByText("10 tracks in the queue")).toBeInTheDocument();
    fireEvent.click(getByRole("button", { name: /open queue/i }));
    expect(chrome.onOpenQueue).toHaveBeenCalledTimes(1);
  });

  it("shows the real source label and a stable HH:MM clock", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 1, 9, 5, 30));
    try {
      const { container } = render(
        <SimpleAudio track={TRACK} state="playing" elapsed={10} volume={50} chrome={makeChrome({ sourceLabel: "AIRPLAY" })}/>,
      );
      const text = container.textContent ?? "";
      expect(text).toContain("AIRPLAY");
      expect(text).toMatch(/09:05/);
      expect(text).not.toMatch(/09:05_/);
    } finally {
      vi.useRealTimers();
    }
  });
});
