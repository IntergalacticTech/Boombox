// ChromeButtons — shared building block each skin renders inside its own
// chrome (top bar, sidebar, etc.) to expose source / queue / skin pickers.
//
// We provide:
//   - <ChromeButtons />   ready-made strip with sensible defaults
//   - <ChromeSourceBtn /> / <ChromeQueueBtn /> / <ChromeSkinBtn />
//                         individual buttons skins can lay out themselves
//
// The buttons live INSIDE the skin's design coordinate space (1280×800), so
// they scale with the skin. At 800×480 viewport (5" screen), 80-px-tall
// buttons in design = 48px on screen — comfortable touch targets.

import type { CSSProperties, ReactNode } from "react";
import type { ChromeApi } from "./skinRegistry";
import { SyncIndicator } from "./SyncIndicator";

export type ChromeTheme = {
  bg?: string;
  fg?: string;
  border?: string;
  font?: string;
  mono?: string;
  /** Pixel height of each button (design coords). Default 56. */
  height?: number;
  /** Border-radius. Default 999 (pill). */
  radius?: number;
  /** Inner padding override. */
  padding?: string;
};

const DEFAULT_THEME: Required<ChromeTheme> = {
  bg: "rgba(255,255,255,0.08)",
  fg: "#fff",
  border: "rgba(255,255,255,0.20)",
  font: "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif",
  mono: "'JetBrains Mono', ui-monospace, monospace",
  height: 56,
  radius: 999,
  padding: "0 18px",
};

function btnStyle(theme: Required<ChromeTheme>): CSSProperties {
  return {
    height: theme.height,
    minWidth: theme.height,
    padding: theme.padding,
    background: theme.bg,
    color: theme.fg,
    border: `1.5px solid ${theme.border}`,
    borderRadius: theme.radius,
    cursor: "pointer",
    display: "inline-flex",
    alignItems: "center",
    gap: 10,
    fontFamily: theme.font,
    fontSize: 14,
    fontWeight: 600,
    letterSpacing: "0.04em",
    whiteSpace: "nowrap",
  };
}

export function ChromeSourceBtn({
  chrome, theme: t = {},
}: {
  chrome: ChromeApi;
  theme?: ChromeTheme;
}) {
  const theme = { ...DEFAULT_THEME, ...t } as Required<ChromeTheme>;
  return (
    <button onClick={chrome.onOpenSource} style={btnStyle(theme)}>
      <span style={{
        width: 12, height: 12, borderRadius: 999,
        background: chrome.sourceColor,
        boxShadow: chrome.sourceLive ? "0 0 8px currentColor" : "none",
        flexShrink: 0,
      }}/>
      <span style={{
        fontFamily: theme.mono,
        fontSize: 12,
        letterSpacing: "0.16em",
      }}>{chrome.sourceLabel}</span>
    </button>
  );
}

export function ChromeQueueBtn({
  chrome, theme: t = {}, label = "QUEUE",
}: {
  chrome: ChromeApi;
  theme?: ChromeTheme;
  label?: string;
}) {
  const theme = { ...DEFAULT_THEME, ...t } as Required<ChromeTheme>;
  return (
    <button onClick={chrome.onOpenQueue} style={btnStyle(theme)}>
      <span style={{
        fontFamily: theme.mono,
        fontSize: 12,
        letterSpacing: "0.16em",
      }}>{label} · {chrome.queueCount}</span>
    </button>
  );
}

export function ChromeSkinBtn({
  chrome, theme: t = {},
}: {
  chrome: ChromeApi;
  theme?: ChromeTheme;
}) {
  const theme = { ...DEFAULT_THEME, ...t } as Required<ChromeTheme>;
  return (
    <button onClick={chrome.onOpenSkinPicker} style={btnStyle(theme)}>
      <span style={{
        fontFamily: theme.mono,
        fontSize: 12,
        letterSpacing: "0.16em",
      }}>SKIN · {chrome.skinName.toUpperCase()}</span>
    </button>
  );
}

export function ChromeSettingsBtn({
  chrome, theme: t = {},
}: {
  chrome: ChromeApi;
  theme?: ChromeTheme;
}) {
  const theme = { ...DEFAULT_THEME, ...t } as Required<ChromeTheme>;
  return (
    <button onClick={chrome.onOpenSettings} aria-label="Settings" style={{
      ...btnStyle(theme),
      padding: "0",
      width: theme.height,
      minWidth: theme.height,
      justifyContent: "center",
    }}>
      <span style={{fontSize: 18, lineHeight: 1}}>⚙</span>
    </button>
  );
}

/** Default 3-button strip with source/queue/skin buttons in a flex row.
 * Skins are free to compose them individually for tighter integration. */
export function ChromeButtons({
  chrome, theme: t = {}, children, align = "spread",
}: {
  chrome: ChromeApi;
  theme?: ChromeTheme;
  /** Optional decorations (clock, status text, etc.) interleaved in the row. */
  children?: ReactNode;
  align?: "spread" | "left" | "right" | "center";
}) {
  const justify =
    align === "left" ? "flex-start"
    : align === "right" ? "flex-end"
    : align === "center" ? "center"
    : "space-between";
  return (
    <div style={{display: "flex", alignItems: "center", gap: 10, justifyContent: justify, width: "100%"}}>
      <ChromeSourceBtn chrome={chrome} theme={t}/>
      <SyncIndicator />
      {children}
      <div style={{display: "flex", gap: 10}}>
        <ChromeQueueBtn chrome={chrome} theme={t}/>
        <ChromeSkinBtn chrome={chrome} theme={t}/>
      </div>
    </div>
  );
}
