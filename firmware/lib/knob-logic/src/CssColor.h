// CSS colour parsing for the boombox theme payload.
//
// The kiosk's skins publish theme tokens as CSS strings: "#rgb", "#rrggbb",
// "#rrggbbaa", "rgb(r, g, b)", "rgba(r, g, b, a)" (a as 0..1 or a %), plus a
// few keywords. Pure C++ (no Arduino), unit-tested natively.
#pragma once
#include <stdint.h>

namespace knob {

struct Rgba {
    uint8_t r = 0, g = 0, b = 0, a = 255;
};

// Returns false (and leaves `out` untouched) on anything it can't parse.
bool parseCssColor(const char* s, Rgba& out);

// Composite `fg` over an opaque `bg` (alpha ignored on bg).
Rgba blendOver(const Rgba& fg, const Rgba& bg);

// Linear mix: t=0 → a, t=255 → b.
Rgba mix(const Rgba& a, const Rgba& b, uint8_t t);

// Relative luminance 0..255 (Rec. 709 weights, no gamma) — enough to pick a
// legible ink for a background.
uint8_t luma(const Rgba& c);

// Packs to 0xRRGGBB.
inline uint32_t toHex(const Rgba& c) {
    return ((uint32_t)c.r << 16) | ((uint32_t)c.g << 8) | c.b;
}

}  // namespace knob
