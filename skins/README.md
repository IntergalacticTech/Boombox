# Boombox Skin Export — Designer Notes

## Tooling
Working in **HTML/React** (not Figma/Sketch/PSD). The interactive mockups live at
`index.html` (a design canvas with all 6 skins side-by-side). Each skin is a
self-contained JSX module: `direction-<skin>.jsx`.

The Figma tokens-export plugin recipe doesn't apply here — but the JSX color/font
constants are the source-of-truth and have been transcribed verbatim into each
`tokens.json` below.

## What's in this export
Per skin folder:
- `tokens.json` — colors, fonts, component variants
- `source.jsx` — the live JSX module (component code + tokens inline)
- `README.md` — skin description and license
Top level:
- `fonts.json` — license info for every font used (all OFL-1.1)

## What's NOT yet in this export — needs your call
1. **800×480 reflow.** Mockups so far are 1280×800 only. Reflow rules (sidebar
   collapses to icon rail? bottom bar wraps? hero shrinks?) need a design pass
   before I can render them. Tell me which rule you want and I'll do it.
2. **WebP backgrounds.** Backgrounds in every skin are CSS gradients, not
   raster — they re-render at any size. If you need flat WebP for the build,
   say which sizes (probably 800×480 + 1280×800) and I'll render them from the
   live mockups.
3. **PNG mockup renders.** Easy to add — just say if you want all 18 (6 skins ×
   3 screens) at both sizes, or a subset.
4. **Library + Settings screens.** Built so far per skin: Now Playing (audio),
   Source Switcher, Now Playing (video). Library and Settings haven't been
   designed yet for any skin. The spec asks for Library + Settings instead of
   Source/Video — confirm which 3 screens you actually want and I'll fill the
   gaps.
5. **Asset SVGs as separate files.** The transport icon set lives inline in
   `shared.jsx` as a single `<Icon name=...>` component (~30 icons, single-
   colour with `currentColor`). I can split it into per-icon `.svg` files on
   request.

## Free-fonts check
All fonts are OFL-1.1 (libre, no attribution required for embedding).
See `fonts.json`.
