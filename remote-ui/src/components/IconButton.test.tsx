import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { IconButton } from "./IconButton";

describe("IconButton", () => {
  it("renders its label and fires onClick", () => {
    const onClick = vi.fn();
    render(<IconButton label="Next" onClick={onClick}>››</IconButton>);
    const btn = screen.getByRole("button", { name: "Next" });
    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("does not fire onClick when disabled", () => {
    const onClick = vi.fn();
    render(
      <IconButton label="Next" onClick={onClick} disabled>››</IconButton>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("applies the primary variant styling flag via data attribute", () => {
    render(
      <IconButton label="Play" onClick={() => {}} primary>▶</IconButton>,
    );
    expect(screen.getByRole("button", { name: "Play" }))
      .toHaveProperty("dataset.primary", "true");
  });
});
