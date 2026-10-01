import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Files, FileBrowser, type FilesClient } from "./Files";
import { ApiProvider, type RemoteApi } from "../lib/api";

const sample = {
  path: "",
  parent: null,
  entries: [
    { name: "Albums", kind: "dir" as const, tracks: 42 },
    { name: "Song.mp3", kind: "file" as const, size: 5 * 1024 * 1024, deletable: true },
  ],
};

function mockApi(overrides: Partial<RemoteApi> = {}): RemoteApi {
  return {
    base: "http://localhost/",
    get: vi.fn().mockResolvedValue(sample),
    post: vi.fn().mockResolvedValue({ ok: true }),
    uploadFiles: vi.fn(),
    ...overrides,
  };
}

function adminClient(overrides: Partial<FilesClient> = {}) {
  return {
    browse: vi.fn().mockResolvedValue(sample),
    upload: vi.fn().mockResolvedValue({ saved: ["uploads/foo.mp3"] }),
    remove: vi.fn().mockResolvedValue({ deleted: "Song.mp3" }),
    ...overrides,
  };
}

describe("Files (household, read-only)", () => {
  it("browses, offers no upload or delete, and points to Storage", async () => {
    const navigate = vi.fn();
    const api = mockApi();
    render(<ApiProvider api={api}><Files navigate={navigate} /></ApiProvider>);
    expect(await screen.findByText("Albums")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("api/remote/files/browse?path=");
    expect(screen.queryByRole("button", { name: "+ Upload" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete Song.mp3" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open Storage" }));
    expect(navigate).toHaveBeenCalledWith("storage");
  });

  it("enters a directory", async () => {
    const api = mockApi();
    render(<ApiProvider api={api}><Files navigate={vi.fn()} /></ApiProvider>);
    fireEvent.click(await screen.findByRole("button", { name: /Albums/ }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("api/remote/files/browse?path=Albums"));
  });
});

describe("FileBrowser with the admin client", () => {
  beforeEach(() => { (globalThis as { confirm?: () => boolean }).confirm = () => true; });
  afterEach(() => { delete (globalThis as { confirm?: () => boolean }).confirm; });

  it("uploads files", async () => {
    const c = adminClient();
    render(<FileBrowser client={c} />);
    await screen.findByText("Albums");
    const input = screen.getByLabelText(/Choose files/i) as HTMLInputElement;
    const file = new File(["x"], "foo.mp3", { type: "audio/mpeg" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(c.upload).toHaveBeenCalledWith([file]));
    expect(await screen.findByText("Uploaded: 1 file(s)")).toBeTruthy();
  });

  it("deletes a file after confirming", async () => {
    const c = adminClient();
    render(<FileBrowser client={c} />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete Song.mp3" }));
    await waitFor(() => expect(c.remove).toHaveBeenCalledWith("Song.mp3"));
  });

  it("a browse failure shows the message and Retry", async () => {
    const c = adminClient({ browse: vi.fn().mockRejectedValueOnce(new Error("library down"))
                                             .mockResolvedValue(sample) });
    render(<FileBrowser client={c} />);
    expect(await screen.findByText("library down")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Albums")).toBeTruthy();
  });
});
