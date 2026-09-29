import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { InstallBanner } from "./InstallBanner";
import { setViewport } from "../test/viewport";

function offerInstall() {
  const e = new Event("beforeinstallprompt") as Event & {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
  };
  e.prompt = async () => {};
  e.userChoice = Promise.resolve({ outcome: "accepted" });
  act(() => { window.dispatchEvent(e); });
}

beforeEach(() => { localStorage.clear(); });

describe("InstallBanner", () => {
  it("offers to install Boombox (not the old remote) edge to edge on a phone", () => {
    render(<InstallBanner />);
    offerInstall();
    const banner = screen.getByRole("region", { name: "Install" });
    expect(banner.textContent).toMatch(/Install Boombox/);
    expect(banner.textContent).not.toMatch(/Remote/);
    expect(banner.style.left).toBe("12px");
    expect(banner.style.right).toBe("12px");
  });

  it("sits over the centre column on desktop, clear of the sidebar and Now panel", () => {
    setViewport(1280);
    render(<InstallBanner />);
    offerInstall();
    const banner = screen.getByRole("region", { name: "Install" });
    expect(banner.style.left).toBe("232px");
    expect(banner.style.right).toBe("372px");
  });
});
