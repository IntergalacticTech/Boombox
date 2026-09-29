import { describe, it, expect, vi, afterEach } from "vitest";
import { makeApi, ApiError, apiErrorMessage } from "./api";

afterEach(() => vi.unstubAllGlobals());

function reply(status: number, body: string) {
  return { ok: status >= 200 && status < 300, status,
    text: async () => body, json: async () => JSON.parse(body),
    blob: async () => new Blob([body]) };
}

describe("makeApi", () => {
  it("calls onUnauthorized on a 401 and still throws ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(401, '{"error":"bad_token"}')));
    const on = vi.fn();
    const api = makeApi("http://pi:8090", "t", on);
    await expect(api.get("api/remote/queue")).rejects.toBeInstanceOf(ApiError);
    await expect(api.post("api/remote/queue", {})).rejects.toBeInstanceOf(ApiError);
    expect(on).toHaveBeenCalledTimes(2);
  });

  it("does not call onUnauthorized for other errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(502, "{}")));
    const on = vi.fn();
    await expect(makeApi("http://pi:8090/", "t", on).get("x")).rejects.toBeInstanceOf(ApiError);
    expect(on).not.toHaveBeenCalled();
  });

  it("getBlob sends the bearer token", async () => {
    const f = vi.fn().mockResolvedValue(reply(200, "img"));
    vi.stubGlobal("fetch", f);
    const blob = await makeApi("http://pi:8090", "tok").getBlob!("api/remote/home/art/a?size=320");
    // jsdom's Blob has no .text(); read it the way a browser without it would.
    const text = await new Promise<string>((resolve) => {
      const fr = new FileReader();
      fr.onload = () => resolve(fr.result as string);
      fr.readAsText(blob);
    });
    expect(text).toBe("img");
    expect(f).toHaveBeenCalledWith("http://pi:8090/api/remote/home/art/a?size=320",
      { headers: { Authorization: "Bearer tok" } });
  });
});

describe("apiErrorMessage", () => {
  it("prefers the server's error text", () => {
    expect(apiErrorMessage(new ApiError(409, '{"ok":false,"error":"kiosk not signed in"}'), "x"))
      .toBe("kiosk not signed in");
  });
  it("falls back with the status, or says unreachable for network errors", () => {
    expect(apiErrorMessage(new ApiError(502, "<html>"), "The Home Library isn't answering"))
      .toBe("The Home Library isn't answering (HTTP 502)");
    expect(apiErrorMessage(new TypeError("offline"), "x")).toBe("Couldn't reach the boombox.");
  });
});
