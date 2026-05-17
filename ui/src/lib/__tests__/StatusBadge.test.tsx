import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { StatusBadge } from "../StatusBadge";

describe("StatusBadge", () => {
  it("renders ⬇ for cached (present + not playing)", () => {
    const { container } = render(
      <StatusBadge cacheStatus="present" isCurrentTrack={false} pinned={false} />
    );
    expect(container.textContent).toContain("⬇");
  });

  it("renders ⚡ when streaming (isCurrentTrack + absent)", () => {
    const { container } = render(
      <StatusBadge cacheStatus="absent" isCurrentTrack={true} pinned={false} />
    );
    expect(container.textContent).toContain("⚡");
  });

  it("renders 📌 when pinned and not yet downloaded", () => {
    const { container } = render(
      <StatusBadge cacheStatus="queued" isCurrentTrack={false} pinned={true} />
    );
    expect(container.textContent).toContain("📌");
  });

  it("renders ☁ for catalog-only (absent, not playing, not pinned)", () => {
    const { container } = render(
      <StatusBadge cacheStatus="absent" isCurrentTrack={false} pinned={false} />
    );
    expect(container.textContent).toContain("☁");
  });

  it("renders ⚠ for error", () => {
    const { container } = render(
      <StatusBadge cacheStatus="error" isCurrentTrack={false} pinned={false} />
    );
    expect(container.textContent).toContain("⚠");
  });

  it("present takes priority over the current-track streaming branch", () => {
    // Cached AND currently playing → still ⬇ since the file is being read locally.
    const { container } = render(
      <StatusBadge cacheStatus="present" isCurrentTrack={true} pinned={true} />
    );
    expect(container.textContent).toContain("⬇");
  });
});
