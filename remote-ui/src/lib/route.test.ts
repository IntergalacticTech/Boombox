import { describe, it, expect } from "vitest";
import { parseHash, hashFor } from "./route";

describe("hash routes", () => {
  it("parses the spec's section routes", () => {
    for (const r of ["now", "music", "video", "search", "playlists", "files", "accounts", "more"]) {
      expect(parseHash(`#/${r}`)).toEqual({ route: r, params: [] });
    }
  });

  it("keeps drill-down params, decoded", () => {
    expect(parseHash("#/music/home/album/al%201")).toEqual(
      { route: "music", params: ["home", "album", "al 1"] });
  });

  it("falls back to now for empty or unknown hashes", () => {
    expect(parseHash("")).toEqual({ route: "now", params: [] });
    expect(parseHash("#/")).toEqual({ route: "now", params: [] });
    expect(parseHash("#/nope/x")).toEqual({ route: "now", params: [] });
  });

  it("survives malformed escapes", () => {
    expect(parseHash("#/video/folder/%E0%A4%A")).toEqual(
      { route: "video", params: ["folder", "%E0%A4%A"] });
  });

  it("round-trips params that contain slashes", () => {
    expect(hashFor("video", ["lib", "abc", "movies"])).toBe("#/video/lib/abc/movies");
    expect(parseHash(hashFor("music", ["home", "album", "a/b"]))).toEqual(
      { route: "music", params: ["home", "album", "a/b"] });
  });
});
