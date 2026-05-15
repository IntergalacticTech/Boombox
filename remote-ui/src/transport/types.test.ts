import { describe, it, expect } from "vitest";
import type { RemoteState, Transport, CommandResult } from "./types";

describe("transport types", () => {
  it("RemoteState accepts a full consolidated payload", () => {
    const s: RemoteState = {
      boombox: { id: "b", name: "Boombox", version: 1 },
      source: "mopidy",
      playing: true,
      track: { title: "T", artist: "A", album: "Al",
               duration_s: 100, position_s: 5 },
      art_hash: "abc",
      art_url: "/api/remote/art/abc.jpg",
      volume: 60,
      muted: false,
      sources_available: ["mopidy", "movies"],
      sleep_timer_s: null,
      recording: false,
      mic_on: false,
      skin: "spectrum",
      theme: { bg: "#000", accent: "#0ff" },
    };
    expect(s.track?.title).toBe("T");
  });

  it("RemoteState accepts a minimal/empty payload", () => {
    const s: RemoteState = {
      boombox: { id: "b", name: "B", version: 1 },
      source: null, playing: false, track: null,
      art_hash: null, art_url: null, volume: null, muted: false,
      sources_available: [], sleep_timer_s: null, recording: false,
      mic_on: false, skin: null, theme: {},
    };
    expect(s.track).toBeNull();
  });

  it("CommandResult models ok and error", () => {
    const ok: CommandResult = { ok: true };
    const bad: CommandResult = { ok: false, error: "remote_disabled" };
    expect(ok.ok).toBe(true);
    expect(bad.error).toBe("remote_disabled");
  });

  it("a Transport implementation satisfies the interface", () => {
    const t: Transport = {
      kind: "http",
      async connect() {},
      disconnect() {},
      onState() { return () => {}; },
      async command() { return { ok: true }; },
    };
    expect(t.kind).toBe("http");
  });
});
