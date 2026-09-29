import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { VideoControls } from "./VideoControls";
import { ApiProvider, type RemoteApi } from "../lib/api";
import { RemoteContextHarness } from "../state/store";
import type { RemoteState } from "../transport/types";
import type { VideoState } from "../lib/video";

const ACTIVE: VideoState = {
  active: true, playing: false, title: "Pilot", item_id: "bb22",
  position_s: 12, duration_s: 888,
  audio_streams: [{ index: 1, label: "English - AAC" }, { index: 2, label: "Commentary" }],
  subtitle_streams: [{ index: 3, label: "English" }],
  audio_index: 1, subtitle_index: -1,
};
const REMOTE: RemoteState = {
  boombox: { id: "b", name: "Box", version: 1 }, source: "movies", playing: false,
  track: null, art_hash: null, art_url: null, volume: 0.3, muted: false,
  sources_available: [], sleep_timer_s: null, recording: false, mic_on: false,
  skin: null, theme: {},
};

function setup(state: VideoState = ACTIVE) {
  const api: RemoteApi = {
    base: "http://pi/",
    get: vi.fn().mockResolvedValue(state),
    post: vi.fn().mockResolvedValue({ ok: true }),
    uploadFiles: vi.fn(),
  };
  const command = vi.fn().mockResolvedValue({ ok: true });
  render(
    <ApiProvider api={api}>
      <RemoteContextHarness state={REMOTE} command={command}>
        <VideoControls pollMs={60_000} />
      </RemoteContextHarness>
    </ApiProvider>,
  );
  return { api, command };
}

describe("VideoControls", () => {
  it("renders nothing when no video is playing", async () => {
    const { api } = setup({ active: false });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("api/remote/video/state"));
    expect(screen.queryByRole("region", { name: /video playing/i })).toBeNull();
  });

  it("shows title and time; transport buttons send commands", async () => {
    const { api } = setup();
    expect(await screen.findByText("Pilot")).toBeTruthy();
    expect(screen.getByText("0:12 / 14:48")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Forward 30 seconds" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "seek", value: 42 }));
    fireEvent.click(screen.getByRole("button", { name: "Play video" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "play_pause" }));
    fireEvent.click(screen.getByRole("button", { name: "Stop video" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "stop" }));
  });

  it("back 30 s never seeks below zero", async () => {
    const { api } = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Back 30 seconds" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "seek", value: 0 }));
  });

  it("picks an audio track and turns subtitles on", async () => {
    const { api } = setup();
    fireEvent.change(await screen.findByLabelText("Audio track"), { target: { value: "2" } });
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "set_audio", value: 2 }));
    fireEvent.change(screen.getByLabelText("Subtitles"), { target: { value: "3" } });
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "set_subtitle", value: 3 }));
  });

  it("turns subtitles off with -1", async () => {
    const { api } = setup({ ...ACTIVE, subtitle_index: 3 });
    fireEvent.change(await screen.findByLabelText("Subtitles"), { target: { value: "-1" } });
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "set_subtitle", value: -1 }));
  });

  it("the scrubber seeks when released", async () => {
    const { api } = setup();
    const slider = await screen.findByLabelText("Position");
    fireEvent.change(slider, { target: { value: "300" } });
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.pointerUp(slider);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "seek", value: 300 }));
  });

  it("volume drives the boombox volume", async () => {
    const { command } = setup();
    fireEvent.change(await screen.findByLabelText("Boombox volume"), { target: { value: "0.4" } });
    expect(command).toHaveBeenCalledWith("volume", 0.4);
  });

  it("shows a command failure", async () => {
    const { api } = setup();
    (api.post as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(await screen.findByRole("button", { name: "Stop video" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("never stacks polls: a slow state request blocks the next one", async () => {
    let release: (v: VideoState) => void = () => {};
    const get = vi.fn().mockImplementation(
      () => new Promise<VideoState>((r) => { release = r; }));
    const api: RemoteApi = { base: "http://pi/", get, post: vi.fn(), uploadFiles: vi.fn() };
    const { unmount } = render(
      <ApiProvider api={api}>
        <RemoteContextHarness state={REMOTE} command={vi.fn()}>
          <VideoControls pollMs={5} />
        </RemoteContextHarness>
      </ApiProvider>,
    );
    await new Promise((r) => setTimeout(r, 60));
    expect(get).toHaveBeenCalledTimes(1);          // still in flight: no second request
    release({ active: false });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));  // next poll only after it resolved
    unmount();
    release({ active: false });
    const calls = get.mock.calls.length;
    await new Promise((r) => setTimeout(r, 60));
    expect(get.mock.calls.length).toBe(calls);     // stopped after unmount
  });
});
