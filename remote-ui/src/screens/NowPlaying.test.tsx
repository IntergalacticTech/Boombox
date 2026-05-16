import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NowPlaying } from "./NowPlaying";
import { RemoteContextHarness } from "../state/store";
import { ApiProvider, type RemoteApi } from "../lib/api";
import type { RemoteState } from "../transport/types";

// NowPlaying now mounts QueueView, which calls useApi(). Tests don't care
// what the queue does — give it a stub that resolves with an empty list.
const stubApi: RemoteApi = {
  base: "http://test/",
  get: vi.fn().mockResolvedValue({ ok: true, tracks: [] }),
  post: vi.fn().mockResolvedValue({ ok: true }),
  uploadFiles: vi.fn(),
};

const playing: RemoteState = {
  boombox: { id: "b", name: "Kitchen", version: 1 },
  source: "mopidy", playing: true,
  track: { title: "Hey Jude", artist: "The Beatles", album: "1967-1970",
           duration_s: 431, position_s: 60 },
  art_hash: null, art_url: null, volume: 0.65, muted: false,
  sources_available: ["mopidy"], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: {},
  shuffle: false, repeat: "off",
};

describe("NowPlaying", () => {
  it("renders the current track", () => {
    render(
      <ApiProvider api={stubApi}>
        <RemoteContextHarness state={playing} command={vi.fn()}>
          <NowPlaying />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    expect(screen.getByText("Hey Jude")).toBeTruthy();
    expect(screen.getByText(/The Beatles/)).toBeTruthy();
  });

  it("the play/pause button fires play_pause", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <ApiProvider api={stubApi}>
        <RemoteContextHarness state={playing} command={command}>
          <NowPlaying />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /pause/i }));
    expect(command).toHaveBeenCalledWith("play_pause");
  });

  it("next / previous fire their commands", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <ApiProvider api={stubApi}>
        <RemoteContextHarness state={playing} command={command}>
          <NowPlaying />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    fireEvent.click(screen.getByRole("button", { name: /previous/i }));
    expect(command).toHaveBeenCalledWith("next");
    expect(command).toHaveBeenCalledWith("previous");
  });

  it("the volume slider fires a volume command with the new value (0..1)", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <ApiProvider api={stubApi}>
        <RemoteContextHarness state={playing} command={command}>
          <NowPlaying />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    fireEvent.change(screen.getByLabelText(/volume/i),
                     { target: { value: "0.8" } });
    expect(command).toHaveBeenCalledWith("volume", 0.8);
  });

  it("volume slider tracks user input optimistically (no snap-back during a drag)", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <ApiProvider api={stubApi}>
        <RemoteContextHarness state={playing} command={command}>
          <NowPlaying />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    // playing.volume = 0.65 initially; user drags to 0.8.
    const slider = screen.getByLabelText(/volume/i) as HTMLInputElement;
    expect(slider.value).toBe("0.65");
    fireEvent.change(slider, { target: { value: "0.8" } });
    // No state push has arrived yet → the slider must reflect the user's input,
    // not snap back to 0.65.
    expect(slider.value).toBe("0.8");
  });

  it("shuffle is rendered toggled when state.shuffle is true", () => {
    const shufOn: RemoteState = { ...playing, shuffle: true };
    render(
      <ApiProvider api={stubApi}>
        <RemoteContextHarness state={shufOn} command={vi.fn()}>
          <NowPlaying />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    expect(screen.getByRole("button", { name: /shuffle/i })
      .getAttribute("aria-pressed")).toBe("true");
  });

  it("shuffle button dispatches shuffle command", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <ApiProvider api={stubApi}>
        <RemoteContextHarness state={playing} command={command}>
          <NowPlaying />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /shuffle/i }));
    expect(command).toHaveBeenCalledWith("shuffle");
  });

  it("renders one chip per source with the active one toggled", () => {
    const withSources: RemoteState = {
      ...playing, source: "airplay",
      sources_available: ["mopidy", "airplay", "spotify"],
    };
    render(
      <ApiProvider api={stubApi}>
        <RemoteContextHarness state={withSources} command={vi.fn()}>
          <NowPlaying />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    const airplay = screen.getByRole("button", { name: /AirPlay/ });
    expect(airplay.getAttribute("aria-pressed")).toBe("true");
    expect(
      screen.getByRole("button", { name: /Library/ })
        .getAttribute("aria-pressed"),
    ).toBe("false");
  });

  it("seek slider commits commit on mouseup with seconds value", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <ApiProvider api={stubApi}>
        <RemoteContextHarness state={playing} command={command}>
          <NowPlaying />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    const seek = screen.getByLabelText(/seek/i) as HTMLInputElement;
    fireEvent.change(seek, { target: { value: "120" } });
    fireEvent.mouseUp(seek, { target: { value: "120" } });
    expect(command).toHaveBeenCalledWith("seek", 120);
  });

  it("clicking a source chip fires command('source', name)", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    const withSources: RemoteState = {
      ...playing, source: "airplay",
      sources_available: ["mopidy", "airplay"],
    };
    render(
      <ApiProvider api={stubApi}>
        <RemoteContextHarness state={withSources} command={command}>
          <NowPlaying />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Library/ }));
    expect(command).toHaveBeenCalledWith("source", "mopidy");
  });

  it("shows a placeholder when nothing is playing", () => {
    const idle: RemoteState = { ...playing, track: null, playing: false };
    render(
      <ApiProvider api={stubApi}>
        <RemoteContextHarness state={idle} command={vi.fn()}>
          <NowPlaying />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    expect(screen.getByText(/nothing playing/i)).toBeTruthy();
  });
});
