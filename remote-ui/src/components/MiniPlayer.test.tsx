import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MiniPlayer } from "./MiniPlayer";
import { RemoteContextHarness } from "../state/store";
import type { RemoteState } from "../transport/types";

const sampleState: RemoteState = {
  boombox: { id: "b", name: "Box", version: 1 },
  source: "mopidy", playing: true,
  track: { title: "Hey Jude", artist: "The Beatles", album: "1967-1970",
           duration_s: 431, position_s: 60 },
  art_hash: null, art_url: null, volume: 0.5, muted: false,
  sources_available: [], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: {},
};

describe("MiniPlayer", () => {
  it("renders nothing when there's no track", () => {
    const idle: RemoteState = { ...sampleState, track: null };
    render(
      <RemoteContextHarness state={idle} command={vi.fn()}>
        <MiniPlayer onOpenNow={vi.fn()} />
      </RemoteContextHarness>,
    );
    expect(screen.queryByRole("region", { name: /mini/i })).toBeNull();
  });

  it("shows the track title and dispatches play_pause", () => {
    const command = vi.fn().mockResolvedValue({ ok: true });
    render(
      <RemoteContextHarness state={sampleState} command={command}>
        <MiniPlayer onOpenNow={vi.fn()} />
      </RemoteContextHarness>,
    );
    expect(screen.getByText("Hey Jude")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /pause/i }));
    expect(command).toHaveBeenCalledWith("play_pause");
  });

  it("title button opens Now Playing", () => {
    const onOpenNow = vi.fn();
    render(
      <RemoteContextHarness state={sampleState} command={vi.fn()}>
        <MiniPlayer onOpenNow={onOpenNow} />
      </RemoteContextHarness>,
    );
    fireEvent.click(screen.getByRole("button", { name: /open now playing/i }));
    expect(onOpenNow).toHaveBeenCalled();
  });
});
