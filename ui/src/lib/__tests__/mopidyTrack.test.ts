import { describe, it, expect } from "vitest";
import { rawToTrack } from "../mopidy";

describe("rawToTrack titles", () => {
  it("labels a nameless proxy stream instead of 'Unknown Track'", () => {
    expect(rawToTrack({ uri: "http://127.0.0.1:6687/api/library/stream/abc" })?.title)
      .toBe("Home Library track");
  });

  it("hides a URL that surfaced as the name", () => {
    const url = "http://127.0.0.1:6687/api/library/stream/abc";
    expect(rawToTrack({ uri: url, name: url })?.title).toBe("Home Library track");
  });

  it("keeps a real tag title", () => {
    expect(rawToTrack({ uri: "local:track:1", name: "Song" })?.title).toBe("Song");
  });

  it("falls back to 'Unknown Track', never a bare non-URL uri", () => {
    expect(rawToTrack({ uri: "local:track:1" })?.title).toBe("Unknown Track");
    expect(rawToTrack({})?.title).toBe("Unknown Track");
  });
});
