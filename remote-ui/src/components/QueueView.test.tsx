import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueueView } from "./QueueView";
import { ApiProvider, type RemoteApi } from "../lib/api";

const sample = {
  ok: true,
  tracks: [
    { tlid: 11, uri: "local:track:a", title: "A", artist: "X",
      album: null, duration_s: 0, playing: true },
    { tlid: 12, uri: "local:track:b", title: "B", artist: "Y",
      album: null, duration_s: 0, playing: false },
  ],
};

function mockApi(overrides: Partial<RemoteApi> = {}): RemoteApi {
  return {
    base: "http://test/",
    get: vi.fn().mockResolvedValue(sample),
    post: vi.fn().mockResolvedValue({ ok: true }),
    uploadFiles: vi.fn(),
    ...overrides,
  };
}

function wrap(api: RemoteApi) {
  return render(<ApiProvider api={api}><QueueView refreshKey={0} /></ApiProvider>);
}

describe("QueueView", () => {
  beforeEach(() => { (globalThis as { confirm?: () => boolean }).confirm = () => true; });
  afterEach(() => { delete (globalThis as { confirm?: () => boolean }).confirm; });

  it("lists tracks with the playing one marked", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => expect(screen.getByText("A")).toBeTruthy());
    expect(screen.getByText("B")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("api/remote/queue");
  });

  it("Jump button POSTs the tlid", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => screen.getByText("B"));
    fireEvent.click(screen.getByRole("button", { name: /Jump to B/ }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/queue/jump", { tlid: 12 },
    ));
  });

  it("Remove button POSTs the tlid", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => screen.getByText("B"));
    fireEvent.click(screen.getByRole("button", { name: /Remove B/ }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/queue/remove", { tlid: 12 },
    ));
  });

  it("Clear button confirms then POSTs /queue/clear", async () => {
    const api = mockApi();
    wrap(api);
    await waitFor(() => screen.getByText("A"));
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/queue/clear",
    ));
  });

  it("empty queue shows the empty state", async () => {
    const api = mockApi({
      get: vi.fn().mockResolvedValue({ ok: true, tracks: [] }),
    });
    wrap(api);
    await waitFor(() =>
      expect(screen.getByText(/nothing queued/i)).toBeTruthy());
  });
});
