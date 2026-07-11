import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Playlists } from "./Playlists";
import { ApiProvider, type RemoteApi } from "../lib/api";

const samplePls = {
  ok: true,
  playlists: [
    { name: "Road Trip",   uri: "m3u:Road%20Trip.m3u" },
    { name: "Workout 80s", uri: "m3u:Workout%2080s.m3u" },
  ],
};

function mockApi(overrides: Partial<RemoteApi> = {}): RemoteApi {
  return {
    base: "http://localhost/",
    get: vi.fn().mockImplementation(async (path: string) => {
      if (path === "api/remote/playlists") return samplePls;
      if (path.endsWith("/items")) {
        return { ok: true, uris: ["local:track:a", "local:track:b"] };
      }
      throw new Error(`unmocked: ${path}`);
    }),
    post: vi.fn().mockResolvedValue({ ok: true }),
    uploadFiles: vi.fn(),
    ...overrides,
  };
}

function wrap(api: RemoteApi) {
  return render(<ApiProvider api={api}><Playlists /></ApiProvider>);
}

describe("Playlists", () => {
  it("lists playlists on mount", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => expect(screen.getByText("Road Trip")).toBeTruthy());
    expect(screen.getByText("Workout 80s")).toBeTruthy();
  });

  it("play button fetches items then queues with play=true", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => screen.getByText("Road Trip"));
    fireEvent.click(screen.getByRole("button", { name: /play Road Trip/i }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/queue",
      { uris: ["local:track:a", "local:track:b"], play: true },
    ));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toMatch(/Playing/));
  });

  it("empty-state when an empty playlist gets played", async () => {
    const api = mockApi({
      get: vi.fn().mockImplementation(async (path: string) => {
        if (path === "api/remote/playlists") return samplePls;
        return { ok: true, uris: [] };
      }),
    });
    wrap(api);
    await waitFor(() => screen.getByText("Road Trip"));
    fireEvent.click(screen.getByRole("button", { name: /play Road Trip/i }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toMatch(/empty/));
    expect(api.post).not.toHaveBeenCalled();
  });

  it("shows empty-state when there are no playlists", async () => {
    const api = mockApi({
      get: vi.fn().mockResolvedValue({ ok: true, playlists: [] }),
    });
    wrap(api);
    await waitFor(() =>
      expect(screen.getByText(/No playlists yet/i)).toBeTruthy());
  });
});
