import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { PinButton } from "../PinButton";

describe("PinButton", () => {
  it("renders unpinned state with aria-pressed=false", () => {
    const { getByRole } = render(
      <PinButton kind="album" id="al1" state="unpinned" onTogglePin={() => {}} />
    );
    const btn = getByRole("button");
    expect(btn.getAttribute("aria-pressed")).toBe("false");
  });

  it("renders cached state with check overlay", () => {
    const { container } = render(
      <PinButton kind="album" id="al1" state="cached" onTogglePin={() => {}} />
    );
    expect(container.textContent).toContain("✓");
  });

  it("renders error state", () => {
    const { container } = render(
      <PinButton kind="album" id="al1" state="error" onTogglePin={() => {}} />
    );
    expect(container.textContent).toContain("⚠");
  });

  it("calls onTogglePin on click (pointerdown+pointerup)", () => {
    const cb = vi.fn();
    const { getByRole } = render(
      <PinButton kind="album" id="al1" state="unpinned" onTogglePin={cb} />
    );
    const btn = getByRole("button");
    fireEvent.pointerDown(btn);
    fireEvent.pointerUp(btn);
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it("touch target is at least 44 x 44 px", () => {
    const { getByRole } = render(
      <PinButton kind="album" id="al1" state="unpinned" onTogglePin={() => {}} />
    );
    const btn = getByRole("button") as HTMLButtonElement;
    expect(parseInt(btn.style.minWidth, 10)).toBeGreaterThanOrEqual(44);
    expect(parseInt(btn.style.minHeight, 10)).toBeGreaterThanOrEqual(44);
  });

  it("downloading state shows the progress label", () => {
    const { container } = render(
      <PinButton kind="track" id="t1" state="downloading" progress={0.42} onTogglePin={() => {}} />
    );
    expect(container.textContent).toContain("42");
  });
});
