import type { CSSProperties } from "react";

/** Music / Video tile grid: as many columns as fit, never narrower than
 *  160 px (min() keeps a single column from overflowing a narrower pane). */
export const TILE_MIN_PX = 160;

export const TILE_GRID: CSSProperties = {
  display: "grid",
  gap: 14,
  gridTemplateColumns: `repeat(auto-fill, minmax(min(${TILE_MIN_PX}px, 100%), 1fr))`,
};
