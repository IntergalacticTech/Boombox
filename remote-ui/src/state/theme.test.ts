import { describe, it, expect, beforeEach } from "vitest";
import { applyTheme } from "./theme";
import type { ThemeVars } from "../transport/types";

beforeEach(() => {
  document.documentElement.removeAttribute("style");
});

describe("applyTheme", () => {
  it("sets each provided theme value as a CSS custom property on :root", () => {
    const theme: ThemeVars = { bg: "#000", accent: "#0ff", font: "Inter" };
    applyTheme(theme);
    const root = document.documentElement;
    expect(root.style.getPropertyValue("--bg")).toBe("#000");
    expect(root.style.getPropertyValue("--accent")).toBe("#0ff");
    expect(root.style.getPropertyValue("--font")).toBe("Inter");
  });

  it("ignores keys not present in the theme object", () => {
    applyTheme({ bg: "#111" });
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("");
  });

  it("an empty theme object is a no-op", () => {
    applyTheme({});
    expect(document.documentElement.getAttribute("style")).toBeNull();
  });
});
