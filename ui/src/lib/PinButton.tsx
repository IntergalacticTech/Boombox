// PinButton — pin/unpin affordance for Home Library album/artist/playlist
// detail rows. Four visual states; long-press for "manage pin" sheet.
//
// Touch targets are >= 44 x 44 px for the 5" resistive kiosk.

import { useRef } from "react";
import type { PinKind } from "./libraryApi";

export type PinButtonState =
  | "unpinned"
  | "downloading"
  | "cached"
  | "error";

type Props = {
  kind: PinKind;
  id: string;
  state: PinButtonState;
  /** 0..1 download progress; only shown in downloading state. */
  progress?: number;
  onTogglePin: () => void;
  onLongPress?: () => void;
};

const LONG_PRESS_MS = 500;

export function PinButton({ state, progress, onTogglePin, onLongPress }: Props) {
  const triggered = useRef(false);
  const timer = useRef<number | null>(null);

  const startPress = () => {
    triggered.current = false;
    if (onLongPress) {
      timer.current = window.setTimeout(() => {
        triggered.current = true;
        onLongPress();
      }, LONG_PRESS_MS);
    }
  };
  const endPress = () => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
    if (!triggered.current) onTogglePin();
  };
  const cancelPress = () => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
    triggered.current = true; // suppress click
  };

  const filled = state !== "unpinned";
  const fillColor =
    state === "error" ? "#ff7a35" :
    state === "downloading" ? "#5be7ff" :
    state === "cached" ? "#9bf2c0" :
    "rgba(255,255,255,0.55)";

  return (
    <button
      type="button"
      aria-label={filled ? "Unpin" : "Pin for offline"}
      aria-pressed={filled}
      onPointerDown={startPress}
      onPointerUp={endPress}
      onPointerLeave={cancelPress}
      onPointerCancel={cancelPress}
      style={{
        width: 44, height: 44, minWidth: 44, minHeight: 44,
        display: "grid", placeItems: "center",
        background: "transparent",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 999,
        cursor: "pointer",
        position: "relative",
        flexShrink: 0,
        color: fillColor,
      }}
    >
      {/* Pin icon — filled when any non-unpinned state */}
      <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M14 2 L22 10 L17 11 L13 15 L15 17 L11 21 L9 19 L5 23 L3 21 L7 17 L5 15 L9 11 L8 9 Z"
          fill={filled ? "currentColor" : "none"}
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>

      {state === "downloading" && (
        <span style={{
          position: "absolute", inset: -2,
          borderRadius: 999,
          border: "2px solid rgba(91,231,255,0.25)",
          borderTopColor: "#5be7ff",
          animation: "boombox-pin-spin 0.9s linear infinite",
          pointerEvents: "none",
        }}>
          <span style={{
            position: "absolute", inset: 0, display: "grid", placeItems: "center",
            fontSize: 9, color: "#5be7ff", fontFamily: "'JetBrains Mono', monospace",
          }}>{progress != null ? `${Math.round(progress * 100)}` : ""}</span>
        </span>
      )}

      {state === "cached" && (
        <span style={{
          position: "absolute", right: 2, bottom: 2,
          width: 14, height: 14, borderRadius: 999,
          background: "#9bf2c0", color: "#0a0a0a",
          display: "grid", placeItems: "center",
          fontSize: 10, fontWeight: 700,
        }}>✓</span>
      )}

      {state === "error" && (
        <span style={{
          position: "absolute", right: 2, bottom: 2,
          width: 14, height: 14, borderRadius: 999,
          background: "#ff7a35", color: "#0a0a0a",
          display: "grid", placeItems: "center",
          fontSize: 10, fontWeight: 700,
        }}>⚠</span>
      )}
    </button>
  );
}
