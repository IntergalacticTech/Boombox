import type { ThemeVars } from "../transport/types";

// theme key → CSS custom property name. The boombox sends the same nine
// keys the kiosk skins use (see services/boombox-state.py's theme payload).
const VAR_MAP: Record<keyof ThemeVars, string> = {
  bg: "--bg",
  panel: "--panel",
  ink: "--ink",
  ink2: "--ink2",
  accent: "--accent",
  accent2: "--accent2",
  rule: "--rule",
  font: "--font",
  mono: "--mono",
};

/** Apply a theme payload as CSS custom properties on :root, so the whole
 *  PWA restyles live when the device skin changes. Missing keys are left
 *  untouched (the index.css fallbacks hold). */
export function applyTheme(theme: ThemeVars): void {
  const root = document.documentElement;
  for (const key of Object.keys(VAR_MAP) as (keyof ThemeVars)[]) {
    const value = theme[key];
    if (typeof value === "string" && value) {
      root.style.setProperty(VAR_MAP[key], value);
    }
  }
}
