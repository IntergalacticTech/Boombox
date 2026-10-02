#include "KnobTheme.h"
#include "CssColor.h"

namespace knob {

namespace {

// Mirrors DEFAULT_THEME in services/boombox-state.py.
const char* const DEF_BG = "#07060c";
const char* const DEF_PANEL = "#100d1c";
const char* const DEF_INK = "#f3f1ff";
const char* const DEF_INK2 = "#9892b8";
const char* const DEF_ACCENT = "#8b5cf6";
const char* const DEF_ACCENT2 = "#5be7ff";
const char* const DEF_RULE = "rgba(255,255,255,0.08)";

lv_color_t toLv(const Rgba& c) { return lv_color_make(c.r, c.g, c.b); }

Rgba parseOr(const String& s, const char* fallback, const Rgba& under) {
    Rgba c;
    if (!s.length() || !parseCssColor(s.c_str(), c)) parseCssColor(fallback, c);
    return c.a == 255 ? c : blendOver(c, under);
}

KnobTheme build(const boombox::ThemeTokens& t) {
    Rgba black;
    const Rgba bg = parseOr(t.bg, DEF_BG, black);
    const Rgba panel = parseOr(t.panel, DEF_PANEL, bg);
    const Rgba ink = parseOr(t.ink, DEF_INK, bg);
    const Rgba ink2 = parseOr(t.ink2, DEF_INK2, bg);
    const Rgba accent = parseOr(t.accent, DEF_ACCENT, bg);
    const Rgba accent2 = parseOr(t.accent2, DEF_ACCENT2, bg);
    const Rgba rule = parseOr(t.rule, DEF_RULE, bg);

    KnobTheme k;
    k.bg = toLv(bg);
    k.panel = toLv(panel);
    k.ink = toLv(ink);
    k.ink2 = toLv(ink2);
    k.accent = toLv(accent);
    k.accent2 = toLv(accent2);
    k.rule = toLv(rule);
    k.light = luma(bg) > 128;
    k.accent_dim = toLv(mix(accent, bg, 170));
    // Unlit arc track: a step from bg toward ink, so it reads on light and
    // dark skins alike (the skin's own `rule` is often near-invisible).
    k.track = toLv(mix(bg, ink, 40));
    const Rgba white{255, 255, 255, 255}, nearBlack{16, 16, 16, 255};
    k.on_accent = toLv(luma(accent) > 150 ? nearBlack : white);
    return k;
}

}  // namespace

KnobTheme defaultTheme() { return build(boombox::ThemeTokens()); }

KnobTheme themeFromTokens(const boombox::ThemeTokens& t) { return build(t); }

}  // namespace knob
