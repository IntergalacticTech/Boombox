import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { MovedHint } from "./MovedHint";

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("MovedHint", () => {
  it("shows once when opened from the old /remote/ address, and strips the marker", () => {
    window.history.replaceState(null, "", "/?from=remote#/now");
    render(<MovedHint />);
    const hint = screen.getByRole("region", { name: /app moved/i });
    expect(hint.textContent).toContain(window.location.host);
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("#/now");
    cleanup();
    window.history.replaceState(null, "", "/?from=remote");
    render(<MovedHint />);
    expect(screen.queryByRole("region", { name: /app moved/i })).toBeNull();
  });

  it("is hidden without the marker", () => {
    render(<MovedHint />);
    expect(screen.queryByRole("region", { name: /app moved/i })).toBeNull();
  });

  it("can be dismissed", () => {
    window.history.replaceState(null, "", "/?from=remote");
    render(<MovedHint />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("region", { name: /app moved/i })).toBeNull();
  });
});
