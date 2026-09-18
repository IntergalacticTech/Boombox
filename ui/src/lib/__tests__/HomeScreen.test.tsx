import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { HomeScreen } from "../HomeScreen";
import { CARDS } from "../sources";
import { SKINS } from "../skinRegistry";

// The real bar opens a Mopidy websocket and polls /api/volume; Home only
// cares that it is offered a slot, so stub it out.
vi.mock("../NowPlayingBar", () => ({
  NowPlayingBar: () => <div data-testid="npb" />,
}));

const theme = SKINS[0].theme;

function renderHome(overrides: Partial<Parameters<typeof HomeScreen>[0]> = {}) {
  const props = {
    theme,
    queueCount: 0,
    onGoPlayer: vi.fn(),
    onOpenLibrary: vi.fn(),
    onOpenSettings: vi.fn(),
    ...overrides,
  };
  render(<HomeScreen {...props} />);
  return props;
}

describe("HomeScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders a tile for every source in sources.ts, plus Settings and Off", () => {
    renderHome();
    for (const c of CARDS) {
      expect(screen.getByRole("button", { name: new RegExp(c.name, "i") })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: /settings/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^off$/i })).toBeInTheDocument();
  });

  it("Music goes to the player view", () => {
    const props = renderHome({ queueCount: 3 });
    fireEvent.click(screen.getByRole("button", { name: /music/i }));
    expect(props.onGoPlayer).toHaveBeenCalled();
  });

  it("Music also opens the library when the queue is empty", () => {
    const props = renderHome({ queueCount: 0 });
    fireEvent.click(screen.getByRole("button", { name: /music/i }));
    expect(props.onOpenLibrary).toHaveBeenCalled();
  });

  it("Off posts to /api/power/sleep", async () => {
    renderHome();
    fireEvent.click(screen.getByRole("button", { name: /^off$/i }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith("/api/power/sleep", expect.objectContaining({ method: "POST" }));
    });
  });

  it("AirPlay switches to the player and raises the shared source overlay", async () => {
    const props = renderHome();
    const seen: string[] = [];
    const handler = (e: Event) => seen.push((e as CustomEvent).detail.source);
    window.addEventListener("boombox:source-overlay", handler as EventListener);
    fireEvent.click(screen.getByRole("button", { name: /airplay/i }));
    window.removeEventListener("boombox:source-overlay", handler as EventListener);
    expect(props.onGoPlayer).toHaveBeenCalled();
    expect(seen).toContain("airplay");
  });

  it("Bluetooth opens pairing as well as the overlay", async () => {
    renderHome();
    fireEvent.click(screen.getByRole("button", { name: /bluetooth/i }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith("/api/bluetooth/pair", expect.objectContaining({ method: "POST" }));
    });
  });

  it("Settings opens the settings drawer", () => {
    const props = renderHome();
    fireEvent.click(screen.getByRole("button", { name: /settings/i }));
    expect(props.onOpenSettings).toHaveBeenCalled();
  });

  it("AUX is informational — it reveals its blurb and changes no view", () => {
    const props = renderHome();
    fireEvent.click(screen.getByRole("button", { name: /aux/i }));
    expect(props.onGoPlayer).not.toHaveBeenCalled();
    expect(screen.getByText(/3\.5 mm/i)).toBeInTheDocument();
  });
});
