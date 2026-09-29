import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { AppShell } from "./AppShell";
import { ApiProvider, type RemoteApi } from "../lib/api";
import { RemoteContextHarness } from "../state/store";
import { setViewport } from "../test/viewport";
import type { RemoteState } from "../transport/types";

const state: RemoteState = {
  boombox: { id: "b", name: "Kitchen", version: 1 },
  source: "mopidy", playing: true,
  track: { title: "Hey Jude", artist: "The Beatles", album: "1967-1970",
           duration_s: 431, position_s: 60 },
  art_hash: null, art_url: null, volume: 0.5, muted: false,
  sources_available: ["mopidy"], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: {},
};

function stubApi(): RemoteApi {
  return {
    base: "http://pi:8090/",
    get: vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/queue") return { ok: true, tracks: [] };
      if (p.startsWith("api/remote/library/browse")) return { ok: true, refs: [] };
      if (p.startsWith("api/remote/playlists")) return { ok: true, playlists: [] };
      if (p.startsWith("api/remote/files")) return { ok: true, entries: [], path: "" };
      return { ok: true };
    }),
    post: vi.fn().mockResolvedValue({ ok: true }),
    uploadFiles: vi.fn(),
  };
}

function renderShell(onOpenSettings = vi.fn()) {
  return render(
    <ApiProvider api={stubApi()}>
      <RemoteContextHarness state={state} command={vi.fn().mockResolvedValue({ ok: true })}>
        <AppShell onOpenSettings={onOpenSettings} />
      </RemoteContextHarness>
    </ApiProvider>,
  );
}

beforeEach(() => {
  window.location.hash = "";
  setViewport(390, 844);
});

describe("AppShell", () => {
  it("phone: bottom tabs, no sidebar, no side panel", () => {
    renderShell();
    const tabs = screen.getByRole("navigation", { name: "Primary" });
    expect(Array.from(tabs.querySelectorAll("button")).map((b) => b.getAttribute("aria-label")))
      .toEqual(["Now", "Music", "Video", "Search", "More"]);
    expect(screen.queryByRole("navigation", { name: "Sections" })).toBeNull();
    expect(screen.queryByRole("complementary", { name: /now playing panel/i })).toBeNull();
  });

  it("desktop: sidebar + always-visible Now Playing panel, no tab bar", () => {
    setViewport(1440, 900);
    window.location.hash = "#/search";
    renderShell();
    expect(screen.getByRole("navigation", { name: "Sections" })).toBeTruthy();
    const panel = screen.getByRole("complementary", { name: /now playing panel/i });
    expect(panel.textContent).toContain("Hey Jude");
    expect(screen.queryByRole("navigation", { name: "Primary" })).toBeNull();
  });

  it("switches layout live when the window crosses 900 px", () => {
    renderShell();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
    setViewport(900, 800);
    expect(screen.getByRole("navigation", { name: "Sections" })).toBeTruthy();
    setViewport(899, 800);
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
  });

  it("routes by hash; tab and sidebar taps update the hash", async () => {
    window.location.hash = "#/search";
    renderShell();
    expect(screen.getByLabelText("Search query")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    await waitFor(() => expect(window.location.hash).toBe("#/more"));
    fireEvent.click(await screen.findByRole("button", { name: "Playlists" }));
    await waitFor(() => expect(window.location.hash).toBe("#/playlists"));
    setViewport(1440, 900);
    fireEvent.click(screen.getByRole("button", { name: "Video" }));
    await waitFor(() => expect(window.location.hash).toBe("#/video"));
  });

  it("shows the mini player on phones everywhere but Now", async () => {
    renderShell();
    expect(screen.queryByRole("region", { name: /mini player/i })).toBeNull();
    window.location.hash = "#/music";
    expect(await screen.findByRole("region", { name: /mini player/i })).toBeTruthy();
  });

  it("opens Settings from More and from the sidebar", async () => {
    const onOpenSettings = vi.fn();
    window.location.hash = "#/more";
    renderShell(onOpenSettings);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    setViewport(1440, 900);
    const sidebar = screen.getByRole("navigation", { name: "Sections" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Settings" }));
    expect(onOpenSettings).toHaveBeenCalledTimes(2);
  });
});
