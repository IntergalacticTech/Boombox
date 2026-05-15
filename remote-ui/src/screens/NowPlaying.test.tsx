import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NowPlaying } from "./NowPlaying";
import { RemoteContextHarness } from "../state/store";
import type { RemoteState } from "../transport/types";

const playing: RemoteState = {
  boombox: { id: "b", name: "Kitchen", version: 1 },
  source: "mopidy", playing: true,
  track: { title: "Hey Jude", artist: "The Beatles", album: "1967-1970",
           duration_s: 431, position_s: 60 },
  art_hash: null, art_url: null, volume: 65, muted: false,
  sources_available: ["mopidy"], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: {},
};

describe("NowPlaying", () => {
  it("renders the current track", () => {
    render(
      <RemoteContextHarness state={playing} command={vi.fn()}>
        <NowPlaying />
      </RemoteContextHarness>,
    );
    expect(screen.getByText("Hey Jude")).toBeTruthy();
    expect(screen.getByText(/The Beatles/)).toBeTruthy();
  });

  it("the play/pause button fires play_pause", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <RemoteContextHarness state={playing} command={command}>
        <NowPlaying />
      </RemoteContextHarness>,
    );
    fireEvent.click(screen.getByRole("button", { name: /pause/i }));
    expect(command).toHaveBeenCalledWith("play_pause");
  });

  it("next / previous fire their commands", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <RemoteContextHarness state={playing} command={command}>
        <NowPlaying />
      </RemoteContextHarness>,
    );
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    fireEvent.click(screen.getByRole("button", { name: /previous/i }));
    expect(command).toHaveBeenCalledWith("next");
    expect(command).toHaveBeenCalledWith("previous");
  });

  it("the volume slider fires a volume command with the new value", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <RemoteContextHarness state={playing} command={command}>
        <NowPlaying />
      </RemoteContextHarness>,
    );
    fireEvent.change(screen.getByLabelText(/volume/i),
                     { target: { value: "80" } });
    expect(command).toHaveBeenCalledWith("volume", 80);
  });

  it("volume slider tracks user input optimistically (no snap-back during a drag)", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <RemoteContextHarness state={playing} command={command}>
        <NowPlaying />
      </RemoteContextHarness>,
    );
    // playing.volume = 65 initially; user drags to 80.
    const slider = screen.getByLabelText(/volume/i) as HTMLInputElement;
    expect(slider.value).toBe("65");
    fireEvent.change(slider, { target: { value: "80" } });
    // No state push has arrived yet → the slider must reflect the user's input,
    // not snap back to 65.
    expect(slider.value).toBe("80");
  });

  it("shows a placeholder when nothing is playing", () => {
    const idle: RemoteState = { ...playing, track: null, playing: false };
    render(
      <RemoteContextHarness state={idle} command={vi.fn()}>
        <NowPlaying />
      </RemoteContextHarness>,
    );
    expect(screen.getByText(/nothing playing/i)).toBeTruthy();
  });
});
