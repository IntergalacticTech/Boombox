import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TabBar } from "./TabBar";

describe("TabBar", () => {
  it("renders all five tabs and marks the active one pressed", () => {
    render(<TabBar active="files" onChange={vi.fn()} />);
    const tabs = screen.getAllByRole("button");
    expect(tabs.length).toBe(5);
    const filesTab = screen.getByRole("button", { name: /files/i });
    expect(filesTab.getAttribute("aria-pressed")).toBe("true");
    expect(
      screen.getByRole("button", { name: /now/i }).getAttribute("aria-pressed"),
    ).toBe("false");
  });

  it("clicking a tab fires onChange with its id", () => {
    const onChange = vi.fn();
    render(<TabBar active="now" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /playlists/i }));
    expect(onChange).toHaveBeenCalledWith("playlists");
  });
});
