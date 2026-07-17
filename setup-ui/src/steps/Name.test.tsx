import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Name } from "./Name";
import type { WizardCtx } from "../App";
import type { SetupApi } from "../lib/api";

function makeCtx(overrides: Partial<WizardCtx> = {}): {
  ctx: WizardCtx; put: ReturnType<typeof vi.fn>; next: ReturnType<typeof vi.fn>;
} {
  const put = vi.fn().mockResolvedValue({
    ok: true, name: "Kitchen", reboot_required: false,
  });
  const next = vi.fn();
  const api = { isKiosk: true, token: null, get: vi.fn(), post: vi.fn(), put } as
    unknown as SetupApi;
  const ctx: WizardCtx = {
    api,
    // Only the fields Name reads matter here.
    status: {} as WizardCtx["status"],
    summary: {
      name: "Boombox", rebootRequired: false, wifiConnected: false,
      wifiSsid: "", wifiIp: "", musicConfigured: false,
      videoMode: "builtin", remoteEnabled: false,
    },
    update: vi.fn(),
    next,
    back: vi.fn(),
    ...overrides,
  };
  return { ctx, put, next };
}

describe("Name step", () => {
  it("blocks an empty name and does not call the API", async () => {
    const { ctx, put } = makeCtx();
    render(<Name ctx={ctx} />);
    fireEvent.change(screen.getByLabelText(/device name/i),
                     { target: { value: "   " } });
    // Next is disabled for an invalid (blank) name.
    const btn = screen.getByRole("button", { name: /next/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(put).not.toHaveBeenCalled();
  });

  it("rejects a name longer than 32 characters (Next disabled)", () => {
    const { ctx } = makeCtx();
    render(<Name ctx={ctx} />);
    fireEvent.change(screen.getByLabelText(/device name/i),
                     { target: { value: "x".repeat(33) } });
    const btn = screen.getByRole("button", { name: /next/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("PUTs identity with the trimmed name + rename_host and advances", async () => {
    const { ctx, put, next } = makeCtx();
    render(<Name ctx={ctx} />);
    fireEvent.change(screen.getByLabelText(/device name/i),
                     { target: { value: "Kitchen" } });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(put).toHaveBeenCalledWith("identity",
      { name: "Kitchen", rename_host: true });
    await waitFor(() => expect(next).toHaveBeenCalled());
  });

  it("shows the server error on a 400 and does not advance", async () => {
    const { ctx, put, next } = makeCtx();
    put.mockResolvedValueOnce({ ok: false, error: "name taken" });
    render(<Name ctx={ctx} />);
    fireEvent.change(screen.getByLabelText(/device name/i),
                     { target: { value: "Kitchen" } });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByText(/name taken/i)).toBeTruthy();
    expect(next).not.toHaveBeenCalled();
  });
});
