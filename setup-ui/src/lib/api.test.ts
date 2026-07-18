import { describe, it, expect, vi, beforeEach } from "vitest";
import { makeApi, parseHashToken } from "./api";

function mockFetch(json: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    text: async () => JSON.stringify(json),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("parseHashToken", () => {
  it("extracts the token from a #t=… fragment", () => {
    expect(parseHashToken("#t=abc123")).toBe("abc123");
  });
  it("extracts the token when other fragment params follow", () => {
    expect(parseHashToken("#foo=1&t=abc123")).toBe("abc123");
  });
  it("url-decodes the token", () => {
    expect(parseHashToken("#t=a%2Fb")).toBe("a/b");
  });
  it("returns null when no token is present", () => {
    expect(parseHashToken("")).toBeNull();
    expect(parseHashToken("#other=1")).toBeNull();
    expect(parseHashToken("#t=")).toBeNull();
  });
});

describe("SetupApi auth attachment", () => {
  it("kiosk (no token): sends no Authorization header and no ?t= query", async () => {
    const fetchFn = mockFetch({ ok: true });
    const api = makeApi("", "localhost"); // on-device, no token → kiosk
    expect(api.isKiosk).toBe(true);

    await api.get("status");

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/setup/status");
    expect(url).not.toContain("t=");
    const headers = (init?.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("phone (token): attaches Bearer header AND ?t= query on every request", async () => {
    const fetchFn = mockFetch({ ok: true });
    const api = makeApi("#t=TOK42", "192.168.1.50"); // LAN client
    expect(api.isKiosk).toBe(false);
    expect(api.token).toBe("TOK42");

    await api.get("status");
    await api.put("identity", { name: "X", rename_host: true });

    const [getUrl, getInit] = fetchFn.mock.calls[0];
    expect(getUrl).toBe("/api/setup/status?t=TOK42");
    expect((getInit.headers as Record<string, string>).Authorization)
      .toBe("Bearer TOK42");

    const [putUrl, putInit] = fetchFn.mock.calls[1];
    expect(putUrl).toBe("/api/setup/identity?t=TOK42");
    expect(putInit.method).toBe("PUT");
    expect((putInit.headers as Record<string, string>).Authorization)
      .toBe("Bearer TOK42");
    expect((putInit.headers as Record<string, string>)["Content-Type"])
      .toBe("application/json");
    expect(JSON.parse(putInit.body as string))
      .toEqual({ name: "X", rename_host: true });
  });

  it("parses a JSON body even on a 400 (validation errors carry a body)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 400,
      text: async () => JSON.stringify({ ok: false, error: "bad_name" }),
    }));
    const api = makeApi("");
    const r = await api.put<{ ok: boolean; error: string }>("identity", {});
    expect(r).toEqual({ ok: false, error: "bad_name" });
  });
});

describe("adoptToken (typed-URL code redemption)", () => {
  it("attaches auth after adopting a token, and isKiosk stays hostname-based", async () => {
    const fetchFn = mockFetch({ ok: true });
    const api = makeApi("", "192.168.1.50"); // LAN visitor, no hash token
    expect(api.isKiosk).toBe(false);
    expect(api.token).toBeNull();

    api.adoptToken("CODE-TOK");
    await api.get("status");

    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/setup/status?t=CODE-TOK");
    expect((init.headers as Record<string, string>).Authorization)
      .toBe("Bearer CODE-TOK");
    expect(api.isKiosk).toBe(false);
  });
});
