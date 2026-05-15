import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Files } from "./Files";
import { ApiProvider, type RemoteApi } from "../lib/api";

const sample = {
  path: "",
  parent: null,
  entries: [
    { name: "Albums", kind: "dir" as const, tracks: 42 },
    { name: "Song.mp3", kind: "file" as const, size: 5 * 1024 * 1024,
      deletable: true },
  ],
};

function mockApi(overrides: Partial<RemoteApi> = {}): RemoteApi {
  return {
    base: "http://test/",
    get: vi.fn().mockResolvedValue(sample),
    post: vi.fn().mockResolvedValue({ deleted: "x" }),
    uploadFiles: vi.fn().mockResolvedValue({ saved: ["uploads/foo.mp3"] }),
    ...overrides,
  };
}

function wrap(api: RemoteApi) {
  return render(<ApiProvider api={api}><Files /></ApiProvider>);
}

describe("Files", () => {
  beforeEach(() => { (globalThis as { confirm?: () => boolean }).confirm = () => true; });
  afterEach(() => { delete (globalThis as { confirm?: () => boolean }).confirm; });

  it("loads the music root on mount", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() =>
      expect(screen.getByText("Albums")).toBeTruthy());
    expect(api.get).toHaveBeenCalledWith(
      "api/remote/files/browse?path=",
    );
    expect(screen.getByText(/Song\.mp3/)).toBeTruthy();
    expect(screen.getByText("(42)")).toBeTruthy();      // dir track count
    expect(screen.getByText(/5\.0 MB/)).toBeTruthy();   // file size
  });

  it("entering a directory re-fetches with the new path", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => screen.getByText("Albums"));
    fireEvent.click(screen.getByText("Albums"));
    expect(api.get).toHaveBeenLastCalledWith(
      "api/remote/files/browse?path=Albums",
    );
  });

  it("delete button POSTs the relative path then refreshes", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => screen.getByText(/Song\.mp3/));
    fireEvent.click(screen.getByLabelText(/Delete Song\.mp3/));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/files/delete", { path: "Song.mp3" },
    ));
  });

  it("Upload click triggers uploadFiles + status message", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => screen.getByText("Albums"));
    const input = screen.getByLabelText(/Choose files/i) as HTMLInputElement;
    const file = new File(["bytes"], "drop.mp3", { type: "audio/mpeg" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(api.uploadFiles).toHaveBeenCalled());
    expect((api.uploadFiles as ReturnType<typeof vi.fn>).mock.calls[0][0])
      .toBe("api/remote/files/upload");
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toMatch(/Uploaded/));
  });

  it("renders the error banner on a failed browse", async () => {
    const api = mockApi({
      get: vi.fn().mockRejectedValue(new Error("network")),
    });
    wrap(api);
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toMatch(/Error/));
  });
});
