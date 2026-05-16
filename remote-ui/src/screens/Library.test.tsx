import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Library } from "./Library";
import { ApiProvider, type RemoteApi } from "../lib/api";

const ROOT = {
  ok: true,
  refs: [
    { uri: "local:directory?type=album",  name: "Albums",  type: "directory" as const },
    { uri: "local:directory?type=artist", name: "Artists", type: "directory" as const },
  ],
};

const ALBUMS = {
  ok: true,
  refs: [
    { uri: "local:album:back_in_black", name: "Back In Black",
      type: "album" as const },
    { uri: "local:album:highway_to_hell", name: "Highway to Hell",
      type: "album" as const },
  ],
};

function mockApi(): RemoteApi {
  return {
    base: "http://test/",
    get: vi.fn().mockImplementation(async (path: string) => {
      if (path === "api/remote/library/browse") return ROOT;
      if (path.startsWith("api/remote/library/browse?uri=local%3Adirectory%3Ftype%3Dalbum")) return ALBUMS;
      if (path.startsWith("api/remote/library/lookup")) {
        return { ok: true, tracks: [
          { uri: "local:track:1" }, { uri: "local:track:2" },
        ] };
      }
      throw new Error(`unmocked: ${path}`);
    }),
    post: vi.fn().mockResolvedValue({ ok: true }),
    uploadFiles: vi.fn(),
  };
}

function wrap(api: RemoteApi) {
  return render(<ApiProvider api={api}><Library /></ApiProvider>);
}

describe("Library", () => {
  it("lists root browse on mount", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => expect(screen.getByText("Albums")).toBeTruthy());
    expect(api.get).toHaveBeenCalledWith("api/remote/library/browse");
  });

  it("drills into a directory and shows breadcrumb", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => screen.getByText("Albums"));
    fireEvent.click(screen.getByText("Albums"));
    await waitFor(() => expect(screen.getByText("Back In Black")).toBeTruthy());
    // Breadcrumb shows Library › Albums
    expect(screen.getAllByText("Albums").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Library")).toBeTruthy();
  });

  it("Play button on an album resolves tracks via lookup then queues with play=true", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => screen.getByText("Albums"));
    fireEvent.click(screen.getByText("Albums"));
    await waitFor(() => screen.getByText("Back In Black"));
    fireEvent.click(screen.getByRole("button", { name: /Play Back In Black/i }));
    await waitFor(() => {
      const calls = (api.get as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0]);
      expect(calls.some((c: string) => c.startsWith("api/remote/library/lookup"))).toBe(true);
      expect(api.post).toHaveBeenCalledWith(
        "api/remote/queue",
        { uris: ["local:track:1", "local:track:2"], play: true },
      );
    });
  });

  it("Up button returns to the previous level", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => screen.getByText("Albums"));
    fireEvent.click(screen.getByText("Albums"));
    await waitFor(() => screen.getByText("Back In Black"));
    fireEvent.click(screen.getByLabelText("Up"));
    await waitFor(() => {
      expect(screen.queryByText("Back In Black")).toBeNull();
      expect(screen.getByText("Artists")).toBeTruthy();
    });
  });
});
