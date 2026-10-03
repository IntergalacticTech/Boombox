import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TabBar, tabForRoute } from "./TabBar";

describe("TabBar", () => {
  it("renders the five phone tabs in order and marks the active one", () => {
    render(<TabBar active="video" onChange={vi.fn()} />);
    expect(screen.getAllByRole("button").map((b) => b.getAttribute("aria-label")))
      .toEqual(["Now", "Music", "Video", "Search", "More"]);
    expect(screen.getByRole("button", { name: "Video" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Now" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("clicking a tab fires onChange with its id", () => {
    const onChange = vi.fn();
    render(<TabBar active="now" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(onChange).toHaveBeenCalledWith("more");
  });

  it("lights More for the sections it holds", () => {
    for (const r of ["playlists", "files", "accounts", "storage", "more"] as const) {
      expect(tabForRoute(r)).toBe("more");
    }
    expect(tabForRoute("music")).toBe("music");
    expect(tabForRoute("now")).toBe("now");
  });
});
