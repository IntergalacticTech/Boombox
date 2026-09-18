import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SleepScreen } from "../SleepScreen";

describe("SleepScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("posts /api/power/wake on a pointer press", async () => {
    render(<SleepScreen />);
    fireEvent.pointerDown(screen.getByTestId("sleep-screen"));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith("/api/power/wake", expect.objectContaining({ method: "POST" }));
    });
  });

  it("wakes on a key press too — any button on the box should do it", async () => {
    render(<SleepScreen />);
    fireEvent.keyDown(window, { key: "a" });
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith("/api/power/wake", expect.objectContaining({ method: "POST" }));
    });
  });

  it("debounces so a held finger does not spam the server", async () => {
    render(<SleepScreen />);
    const el = screen.getByTestId("sleep-screen");
    fireEvent.pointerDown(el);
    fireEvent.touchStart(el);
    fireEvent.pointerDown(el);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
  });
});
