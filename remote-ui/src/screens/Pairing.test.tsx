import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Pairing } from "./Pairing";

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("Pairing screen", () => {
  it("redeems the PIN and calls onPaired with the new pairing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true, auth_token: "tok99", boombox_name: "Garage",
      }),
    }));
    const onPaired = vi.fn();
    render(<Pairing onPaired={onPaired} />);

    fireEvent.change(screen.getByLabelText(/boombox address/i),
                     { target: { value: "192.168.1.9" } });
    fireEvent.change(screen.getByLabelText(/pin/i),
                     { target: { value: "654321" } });
    fireEvent.click(screen.getByRole("button", { name: /pair/i }));

    await waitFor(() => expect(onPaired).toHaveBeenCalled());
    expect(onPaired).toHaveBeenCalledWith({
      base: "http://192.168.1.9:8090", token: "tok99", name: "Garage",
    });
  });

  it("normalizeBase preserves an already-ported host (no double :8090)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true, auth_token: "tok42", boombox_name: "Loft",
      }),
    }));
    const onPaired = vi.fn();
    render(<Pairing onPaired={onPaired} />);
    fireEvent.change(screen.getByLabelText(/boombox address/i),
                     { target: { value: "192.168.1.9:9090" } });
    fireEvent.change(screen.getByLabelText(/pin/i),
                     { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /pair/i }));
    await waitFor(() => expect(onPaired).toHaveBeenCalled());
    expect(onPaired).toHaveBeenCalledWith({
      base: "http://192.168.1.9:9090",
      token: "tok42",
      name: "Loft",
    });
  });

  it("shows an error message when the PIN is rejected", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 403,
      json: async () => ({ ok: false, error: "bad_pin" }),
    }));
    render(<Pairing onPaired={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/boombox address/i),
                     { target: { value: "pi" } });
    fireEvent.change(screen.getByLabelText(/pin/i),
                     { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: /pair/i }));
    await waitFor(() =>
      expect(screen.getByText(/incorrect pin/i)).toBeTruthy());
  });
});
