import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Video } from "./Video";
import { ApiProvider, ApiError, type RemoteApi } from "../lib/api";
import { RemoteContextHarness } from "../state/store";
import type { VideoItem } from "../lib/video";

function item(o: Partial<VideoItem>): VideoItem {
  return { id: "0", name: "", type: "Movie", collection_type: null, is_folder: false,
    year: null, runtime_s: 0, series_name: null, season: null, episode: null,
    overview: null, has_image: false, played: false, progress: null, resume_s: 0, ...o };
}

const MOVIES_LIB = item({ id: "a1b2", name: "Movies", type: "CollectionFolder",
                          collection_type: "movies", is_folder: true });
const SHOWS_LIB = item({ id: "a3b4", name: "Shows", type: "CollectionFolder",
                         collection_type: "tvshows", is_folder: true });
const EPISODE = item({ id: "bb22", name: "Pilot", type: "Episode", series_name: "Show",
                       season: 1, episode: 2, runtime_s: 2600, resume_s: 754, progress: 29 });
const MOVIE = item({ id: "aa11", name: "Big Buck Bunny", year: 2008, runtime_s: 596,
                     overview: "A giant rabbit." });
const SERIES = item({ id: "c3d4", name: "Show", type: "Series", is_folder: true });

function mockApi(overrides: Partial<RemoteApi> = {}): RemoteApi {
  return {
    base: "http://pi/",
    get: vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/video/state") return { active: false };
      if (p === "api/remote/video/views") return { ok: true, items: [MOVIES_LIB, SHOWS_LIB] };
      if (p === "api/remote/video/resume") return { ok: true, items: [EPISODE] };
      if (p === "api/remote/video/items?parent_id=a1b2&type=Movie&start=0&limit=60") {
        return { ok: true, items: [MOVIE], total: 61, start: 0 };
      }
      if (p === "api/remote/video/items?parent_id=a1b2&type=Movie&start=60&limit=60") {
        return { ok: true, items: [item({ id: "aa12", name: "Sintel" })], total: 61, start: 60 };
      }
      if (p === "api/remote/video/items?parent_id=a3b4&type=Series&start=0&limit=60") {
        return { ok: true, items: [SERIES], total: 1, start: 0 };
      }
      throw new Error(`unmocked ${p}`);
    }),
    post: vi.fn().mockResolvedValue({ ok: true }),
    ...overrides,
  };
}

function wrap(api: RemoteApi, params: string[], navigate = vi.fn()) {
  return render(
    <ApiProvider api={api}>
      <RemoteContextHarness state={null} command={vi.fn()}>
        <Video params={params} navigate={navigate} />
      </RemoteContextHarness>
    </ApiProvider>,
  );
}

describe("Video", () => {
  it("home shows Continue watching and libraries; a library opens its grid", async () => {
    const navigate = vi.fn();
    wrap(mockApi(), [], navigate);
    expect(await screen.findByText("Continue watching")).toBeTruthy();
    expect(screen.getByText("Pilot")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Movies/ }));
    expect(navigate).toHaveBeenCalledWith("video", ["lib", "a1b2", "movies"]);
  });

  it("a library grid pages with Load more", async () => {
    wrap(mockApi(), ["lib", "a1b2", "movies"]);
    expect(await screen.findByText("Big Buck Bunny")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Load more/ }));
    expect(await screen.findByText("Sintel")).toBeTruthy();
    expect(screen.getByText("Big Buck Bunny")).toBeTruthy();
  });

  it("series open as folders", async () => {
    const navigate = vi.fn();
    wrap(mockApi(), ["lib", "a3b4", "tvshows"], navigate);
    fireEvent.click(await screen.findByRole("button", { name: /Show/ }));
    expect(navigate).toHaveBeenCalledWith("video", ["folder", "c3d4"]);
  });

  it("a movie opens a sheet; Play on the boombox posts the item", async () => {
    const api = mockApi();
    wrap(api, ["lib", "a1b2", "movies"]);
    fireEvent.click(await screen.findByRole("button", { name: /Big Buck Bunny/ }));
    const sheet = await screen.findByRole("dialog", { name: "Big Buck Bunny" });
    expect(sheet.textContent).toContain("A giant rabbit.");
    fireEvent.click(screen.getByRole("button", { name: "Play on the boombox" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/play", { item_id: "aa11" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("resume starts at the saved position", async () => {
    const api = mockApi();
    wrap(api, []);
    fireEvent.click(await screen.findByRole("button", { name: /Pilot/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Resume from 12:34" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/play", { item_id: "bb22", start_ticks: 7_540_000_000 }));
  });

  it("a play failure shows the server's message and keeps the sheet", async () => {
    const post = vi.fn().mockRejectedValue(new ApiError(504,
      '{"ok":false,"error":"the boombox\'s video player didn\'t open — try again"}'));
    wrap(mockApi({ post }), ["lib", "a1b2", "movies"]);
    fireEvent.click(await screen.findByRole("button", { name: /Big Buck Bunny/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Play on the boombox" }));
    expect(await screen.findByText(/video player didn't open/)).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("kiosk not signed in: message, Accounts hint, Retry", async () => {
    let fail = true;
    const base = mockApi();
    const get = vi.fn().mockImplementation(async (p: string) => {
      if (fail && (p === "api/remote/video/views" || p === "api/remote/video/resume")) {
        throw new ApiError(409, '{"ok":false,"error":"kiosk not signed in"}');
      }
      return (base.get as (p: string) => Promise<unknown>)(p);
    });
    wrap(mockApi({ get }), []);
    expect(await screen.findByText("kiosk not signed in")).toBeTruthy();
    expect(screen.getByText(/Admin → Accounts/)).toBeTruthy();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Continue watching")).toBeTruthy();
  });

  it("video server not configured shows a message", async () => {
    const get = vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/video/state") return { active: false };
      throw new ApiError(503, '{"ok":false,"error":"video server not configured"}');
    });
    wrap(mockApi({ get }), []);
    expect(await screen.findByText("video server not configured")).toBeTruthy();
  });
});
