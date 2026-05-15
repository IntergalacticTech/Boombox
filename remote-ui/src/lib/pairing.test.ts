import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  redeemPin, loadPairing, savePairing, clearPairing,
} from "./pairing";

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("pairing", () => {
  it("savePairing / loadPairing round-trips base + token", () => {
    savePairing({ base: "http://pi:8090", token: "tok", name: "Boombox" });
    expect(loadPairing()).toEqual({
      base: "http://pi:8090", token: "tok", name: "Boombox",
    });
  });

  it("loadPairing returns null when nothing is stored", () => {
    expect(loadPairing()).toBeNull();
  });

  it("clearPairing removes the stored pairing", () => {
    savePairing({ base: "http://pi:8090", token: "t", name: "B" });
    clearPairing();
    expect(loadPairing()).toBeNull();
  });

  it("redeemPin POSTs the PIN and returns the token on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true, auth_token: "newtok", boombox_name: "Kitchen",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const res = await redeemPin("http://pi:8090", "123456", "my phone");
    expect(res).toEqual({ ok: true, token: "newtok", name: "Kitchen" });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://pi:8090/api/remote/pair",
      expect.objectContaining({ method: "POST" }),
    );
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toEqual({ pin: "123456", label: "my phone" });
  });

  it("redeemPin surfaces a bad-pin error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 403,
      json: async () => ({ ok: false, error: "bad_pin" }),
    }));
    const res = await redeemPin("http://pi:8090", "000000", "x");
    expect(res).toEqual({ ok: false, error: "bad_pin" });
  });

  it("redeemPin surfaces remote_disabled", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 403,
      json: async () => ({ ok: false, error: "remote_disabled" }),
    }));
    const res = await redeemPin("http://pi:8090", "123456", "x");
    expect(res).toEqual({ ok: false, error: "remote_disabled" });
  });

  it("redeemPin surfaces an unreachable boombox", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    const res = await redeemPin("http://pi:8090", "123456", "x");
    expect(res).toEqual({ ok: false, error: "unreachable" });
  });
});
