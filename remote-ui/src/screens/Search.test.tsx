import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Search } from "./Search";
import { ApiProvider, type RemoteApi } from "../lib/api";

const sample = {
  ok: true,
  tracks: [
    { uri: "local:track:1", title: "Heat of the Moment", artist: "Asia",
      album: "Asia", duration_s: 230 },
    { uri: "local:track:2", title: "Don't Stop Believin'", artist: "Journey",
      album: "Escape", duration_s: 251 },
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

function wrap(api: RemoteApi) {
  return render(<ApiProvider api={api}><Search /></ApiProvider>);
}

describe("Search", () => {
  it("submits the query and renders results", async () => {
    const api = mockApi();
    wrap(api);
    fireEvent.change(screen.getByLabelText(/search query/i),
                     { target: { value: "Asia" } });
    fireEvent.click(screen.getByRole("button", { name: /go/i }));
    await waitFor(() =>
      expect(screen.getByText("Heat of the Moment")).toBeTruthy());
    expect(api.get).toHaveBeenCalledWith(
      "api/remote/library/search?q=Asia&field=any",
    );
    expect(screen.getByText(/2 results/)).toBeTruthy();
  });

  it("track ▶ button queues the single track with play=true", async () => {
    const api = mockApi();
    wrap(api);
    fireEvent.change(screen.getByLabelText(/search query/i),
                     { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /go/i }));
    await waitFor(() => screen.getByText("Heat of the Moment"));
    fireEvent.click(screen.getByRole("button", { name: /play Heat/i }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/queue", { uris: ["local:track:1"], play: true },
    ));
  });

  it("'+' button queues without starting playback", async () => {
    const api = mockApi();
    wrap(api);
    fireEvent.change(screen.getByLabelText(/search query/i),
                     { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /go/i }));
    await waitFor(() => screen.getByText("Don't Stop Believin'"));
    fireEvent.click(screen.getByRole("button", { name: /queue Don't Stop/i }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/queue", { uris: ["local:track:2"], play: false },
    ));
  });

  it("'Play all' queues every result with play=true", async () => {
    const api = mockApi();
    wrap(api);
    fireEvent.change(screen.getByLabelText(/search query/i),
                     { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /go/i }));
    await waitFor(() => screen.getByText("Heat of the Moment"));
    fireEvent.click(screen.getByRole("button", { name: /play all/i }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/queue",
      { uris: ["local:track:1", "local:track:2"], play: true },
    ));
  });

  it("renders empty-state when results are zero", async () => {
    const api = mockApi({
      get: vi.fn().mockResolvedValue({ ok: true, tracks: [] }),
    });
    wrap(api);
    fireEvent.change(screen.getByLabelText(/search query/i),
                     { target: { value: "obscure" } });
    fireEvent.click(screen.getByRole("button", { name: /go/i }));
    await waitFor(() => expect(screen.getByText(/no results/i)).toBeTruthy());
  });
});
