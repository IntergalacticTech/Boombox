import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { AuthedImg } from "./AuthedImg";
import { TILE_GRID } from "./grid";
import { ApiProvider, type RemoteApi } from "../lib/api";

let create: ReturnType<typeof vi.fn>;
let revoke: ReturnType<typeof vi.fn>;

beforeEach(() => {
  create = vi.fn(() => "blob:poster");
  revoke = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { value: create, configurable: true, writable: true });
  Object.defineProperty(URL, "revokeObjectURL", { value: revoke, configurable: true, writable: true });
});

function api(getBlob?: RemoteApi["getBlob"]): RemoteApi {
  return { base: "http://pi/", get: vi.fn(), post: vi.fn(), getBlob };
}

describe("AuthedImg", () => {
  it("fetches with the token, shows an object URL and revokes it on unmount", async () => {
    const getBlob = vi.fn().mockResolvedValue(new Blob(["x"]));
    const { container, unmount } = render(
      <ApiProvider api={api(getBlob)}><AuthedImg path="api/remote/home/art/a?size=320" alt="" /></ApiProvider>);
    await waitFor(() => expect(container.querySelector("img")?.getAttribute("src")).toBe("blob:poster"));
    expect(getBlob).toHaveBeenCalledWith("api/remote/home/art/a?size=320");
    unmount();
    expect(revoke).toHaveBeenCalledWith("blob:poster");
  });

  it("stays a placeholder without a path, without getBlob, or on failure", async () => {
    const failing = vi.fn().mockRejectedValue(new Error("404"));
    const { container } = render(
      <ApiProvider api={api(failing)}><AuthedImg path="api/x" alt="" /></ApiProvider>);
    await waitFor(() => expect(failing).toHaveBeenCalled());
    expect(container.querySelector("img")).toBeNull();
    const none = render(<ApiProvider api={api()}><AuthedImg path="api/x" alt="" /></ApiProvider>);
    expect(none.container.querySelector("img")).toBeNull();
    const noPath = vi.fn();
    render(<ApiProvider api={api(noPath)}><AuthedImg path={null} alt="" /></ApiProvider>);
    expect(noPath).not.toHaveBeenCalled();
  });

  it("tile grid never goes below 160 px columns", () => {
    expect(String(TILE_GRID.gridTemplateColumns)).toContain("160px");
  });
});
