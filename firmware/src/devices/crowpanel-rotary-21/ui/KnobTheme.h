// Knob colours, derived from the boombox skin's theme tokens.
#pragma once
#include <lvgl.h>
#include "state/BoomboxState.h"

namespace knob {

struct KnobTheme {
    lv_color_t bg, panel, ink, ink2, accent, accent2, rule;
    lv_color_t accent_dim;   // accent faded toward bg (muted volume arc)
    lv_color_t track;        // unlit part of the arcs
    lv_color_t on_accent;    // legible text on an accent fill
    bool light;              // bg is light (affects nothing structural)
};

// The kiosk's default "Simple" skin — dark violet. Used until the boombox
// sends a theme, and for any token that fails to parse.
KnobTheme defaultTheme();

// Build from CSS tokens; unparseable/missing tokens fall back per-token.
KnobTheme themeFromTokens(const boombox::ThemeTokens& t);

}  // namespace knob
