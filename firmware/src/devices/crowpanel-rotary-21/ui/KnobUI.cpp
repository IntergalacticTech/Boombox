#include "KnobUI.h"

#include <math.h>

namespace knob {

namespace {

constexpr int W = 480;
constexpr int CX = 240;

// Volume arc on the rim: 270° sweep with the gap at the bottom, where the
// volume read-out sits.
constexpr int VOL_D = 464;
constexpr int VOL_W = 14;
constexpr int PROG_D = 420;
constexpr int PROG_W = 4;
constexpr int ARC_START = 135;
constexpr int ARC_END = 45;

constexpr int CHIP_D = 92;
constexpr int CHIP_R = 166;   // centre-to-chip-centre radius

lv_obj_t* group(lv_obj_t* parent) {
    lv_obj_t* g = lv_obj_create(parent);
    lv_obj_remove_style_all(g);
    lv_obj_set_size(g, W, W);
    lv_obj_set_pos(g, 0, 0);
    lv_obj_remove_flag(g, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(g, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(g, LV_OBJ_FLAG_HIDDEN);
    return g;
}

lv_obj_t* label(lv_obj_t* parent, const lv_font_t* font, const char* text = "") {
    lv_obj_t* l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_text(l, text);
    return l;
}

// lv_label_set_text invalidates even when the text is unchanged.
void setText(lv_obj_t* l, const char* text) {
    const char* cur = lv_label_get_text(l);
    if (cur && strcmp(cur, text) == 0) return;
    lv_label_set_text(l, text);
}

void show(lv_obj_t* o, bool on) {
    const bool hidden = lv_obj_has_flag(o, LV_OBJ_FLAG_HIDDEN);
    if (on && hidden) lv_obj_remove_flag(o, LV_OBJ_FLAG_HIDDEN);
    if (!on && !hidden) lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
}

lv_obj_t* rimArc(lv_obj_t* parent, int d, int w) {
    lv_obj_t* a = lv_arc_create(parent);
    lv_obj_set_size(a, d, d);
    lv_obj_center(a);
    lv_arc_set_bg_angles(a, ARC_START, ARC_END);
    lv_arc_set_range(a, 0, 100);
    lv_arc_set_value(a, 0);
    lv_obj_remove_flag(a, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_arc_width(a, w, LV_PART_MAIN);
    lv_obj_set_style_arc_width(a, w, LV_PART_INDICATOR);
    lv_obj_set_style_arc_rounded(a, true, LV_PART_MAIN);
    lv_obj_set_style_arc_rounded(a, true, LV_PART_INDICATOR);
    lv_obj_set_style_pad_all(a, 0, LV_PART_MAIN);
    return a;
}

}  // namespace

// ------------------------------------------------------------------ build
void KnobUI::build() {
    _t = defaultTheme();
    _scr = lv_screen_active();
    lv_obj_remove_flag(_scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_opa(_scr, LV_OPA_COVER, 0);

    // ---- test (bring-up colour bars + ring)
    _g_test = group(_scr);
    static const uint32_t BARS[8] = {0xFFFFFF, 0xFFFF00, 0x00FFFF, 0x00FF00,
                                     0xFF00FF, 0xFF0000, 0x0000FF, 0x000000};
    for (int i = 0; i < 8; i++) {
        lv_obj_t* b = lv_obj_create(_g_test);
        lv_obj_remove_style_all(b);
        lv_obj_set_size(b, 60, W);
        lv_obj_set_pos(b, i * 60, 0);
        lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(b, lv_color_hex(BARS[i]), 0);
    }
    lv_obj_t* ring = rimArc(_g_test, 440, 18);
    lv_arc_set_value(ring, 66);
    lv_obj_set_style_arc_color(ring, lv_color_hex(0x202020), LV_PART_MAIN);
    lv_obj_set_style_arc_color(ring, lv_color_hex(0xFF8800), LV_PART_INDICATOR);
    lv_obj_t* tl = label(_g_test, &lv_font_montserrat_28, "BRING-UP");
    lv_obj_set_style_text_color(tl, lv_color_black(), 0);
    lv_obj_set_style_bg_color(tl, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(tl, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(tl, 8, 0);
    lv_obj_center(tl);

    // ---- searching
    _g_search = group(_scr);
    _s_title = label(_g_search, &lv_font_montserrat_28);
    lv_obj_align(_s_title, LV_ALIGN_CENTER, 0, -70);
    _s_status = label(_g_search, &lv_font_montserrat_20);
    lv_obj_set_width(_s_status, 320);
    lv_label_set_long_mode(_s_status, LV_LABEL_LONG_WRAP);
    lv_obj_align(_s_status, LV_ALIGN_CENTER, 0, -20);
    _s_spinner = lv_spinner_create(_g_search);
    lv_spinner_set_anim_params(_s_spinner, 1200, 90);
    lv_obj_set_size(_s_spinner, 64, 64);
    lv_obj_align(_s_spinner, LV_ALIGN_CENTER, 0, 70);
    lv_obj_set_style_arc_width(_s_spinner, 6, LV_PART_MAIN);
    lv_obj_set_style_arc_width(_s_spinner, 6, LV_PART_INDICATOR);

    // ---- pair
    _g_pair = group(_scr);
    _p_title = label(_g_pair, &lv_font_montserrat_28, "Pair this knob");
    lv_obj_align(_p_title, LV_ALIGN_CENTER, 0, -135);
    _p_hint = label(_g_pair, &lv_font_montserrat_16,
                    "Enter the PIN shown on the boombox");
    lv_obj_set_width(_p_hint, 320);
    lv_label_set_long_mode(_p_hint, LV_LABEL_LONG_WRAP);
    lv_obj_align(_p_hint, LV_ALIGN_CENTER, 0, -92);
    const int cw = 50, ch = 72, gap = 8;
    const int x0 = CX - (6 * cw + 5 * gap) / 2;
    for (int i = 0; i < 6; i++) {
        lv_obj_t* c = lv_obj_create(_g_pair);
        lv_obj_remove_style_all(c);
        lv_obj_set_size(c, cw, ch);
        lv_obj_set_pos(c, x0 + i * (cw + gap), 240 - ch / 2 - 10);
        lv_obj_set_style_radius(c, 10, 0);
        lv_obj_set_style_bg_opa(c, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(c, 2, 0);
        lv_obj_remove_flag(c, LV_OBJ_FLAG_SCROLLABLE);
        _p_cells[i] = c;
        _p_digits[i] = label(c, &lv_font_montserrat_40, "0");
        lv_obj_center(_p_digits[i]);
    }
    _p_help = label(_g_pair, &lv_font_montserrat_14,
                    "Turn to change, click for next\nhold to go back");
    lv_obj_align(_p_help, LV_ALIGN_CENTER, 0, 62);
    _p_status = label(_g_pair, &lv_font_montserrat_20, "");
    lv_obj_set_width(_p_status, 320);
    lv_label_set_long_mode(_p_status, LV_LABEL_LONG_WRAP);
    lv_obj_align(_p_status, LV_ALIGN_CENTER, 0, 118);
    _p_name = label(_g_pair, &lv_font_montserrat_14, "");
    lv_obj_align(_p_name, LV_ALIGN_CENTER, 0, 165);

    // ---- face
    _g_face = group(_scr);
    _vol_arc = rimArc(_g_face, VOL_D, VOL_W);
    lv_obj_set_style_pad_all(_vol_arc, 5, LV_PART_KNOB);
    lv_obj_set_style_border_width(_vol_arc, 3, LV_PART_KNOB);
    lv_obj_set_style_shadow_width(_vol_arc, 0, LV_PART_KNOB);
    _prog_arc = rimArc(_g_face, PROG_D, PROG_W);
    lv_obj_set_style_bg_opa(_prog_arc, LV_OPA_TRANSP, LV_PART_KNOB);
    lv_obj_set_style_pad_all(_prog_arc, 0, LV_PART_KNOB);
    lv_obj_set_style_border_width(_prog_arc, 0, LV_PART_KNOB);
    lv_obj_set_style_shadow_width(_prog_arc, 0, LV_PART_KNOB);
    lv_arc_set_range(_prog_arc, 0, 1000);
    show(_prog_arc, false);

    _f_vol_label = label(_g_face, &lv_font_montserrat_20, "");
    lv_obj_align(_f_vol_label, LV_ALIGN_CENTER, 0, 200);

    _f_center = lv_obj_create(_g_face);
    lv_obj_remove_style_all(_f_center);
    lv_obj_set_size(_f_center, W, W);
    lv_obj_remove_flag(_f_center, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(_f_center, LV_OBJ_FLAG_CLICKABLE);

    _f_col = lv_obj_create(_f_center);
    lv_obj_remove_style_all(_f_col);
    lv_obj_set_size(_f_col, 340, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(_f_col, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(_f_col, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(_f_col, 10, 0);
    lv_obj_remove_flag(_f_col, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(_f_col, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_align(_f_col, LV_ALIGN_CENTER, 0, -28);

    _f_source = label(_f_col, &lv_font_montserrat_16, "");
    lv_obj_set_style_text_letter_space(_f_source, 3, 0);
    _f_title = label(_f_col, &lv_font_montserrat_32, "");
    lv_obj_set_width(_f_title, 330);
    lv_label_set_long_mode(_f_title, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_line_space(_f_title, 2, 0);
    _f_artist = label(_f_col, &lv_font_montserrat_20, "");
    lv_obj_set_width(_f_artist, 300);
    lv_label_set_long_mode(_f_artist, LV_LABEL_LONG_DOT);

    _f_glyph_ring = lv_obj_create(_f_center);
    lv_obj_remove_style_all(_f_glyph_ring);
    lv_obj_set_size(_f_glyph_ring, 64, 64);
    lv_obj_set_style_radius(_f_glyph_ring, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(_f_glyph_ring, 2, 0);
    lv_obj_remove_flag(_f_glyph_ring, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(_f_glyph_ring, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_align(_f_glyph_ring, LV_ALIGN_CENTER, 0, 118);
    _f_glyph = label(_f_glyph_ring, &lv_font_montserrat_24, LV_SYMBOL_PLAY);
    lv_obj_center(_f_glyph);

    // Invisible tap target over the centre: tap = play/pause.
    _f_tap = lv_obj_create(_f_center);
    lv_obj_remove_style_all(_f_tap);
    lv_obj_set_size(_f_tap, 300, 300);
    lv_obj_set_style_radius(_f_tap, LV_RADIUS_CIRCLE, 0);
    lv_obj_center(_f_tap);
    lv_obj_add_flag(_f_tap, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(_f_tap, _centerTapCb, LV_EVENT_CLICKED, this);

    // ---- menu (child of the face so the volume arc stays visible)
    _g_menu = group(_g_face);
    _m_title = label(_g_menu, &lv_font_montserrat_24, "");
    lv_obj_set_width(_m_title, 220);
    lv_label_set_long_mode(_m_title, LV_LABEL_LONG_DOT);
    lv_obj_align(_m_title, LV_ALIGN_CENTER, 0, -14);
    _m_sub = label(_g_menu, &lv_font_montserrat_16, "");
    lv_obj_set_width(_m_sub, 200);
    lv_label_set_long_mode(_m_sub, LV_LABEL_LONG_DOT);
    lv_obj_align(_m_sub, LV_ALIGN_CENTER, 0, 18);
    _m_hint = label(_g_menu, &lv_font_montserrat_14, "hold to close");
    lv_obj_align(_m_hint, LV_ALIGN_CENTER, 0, 206);
    _m_tap = lv_obj_create(_g_menu);
    lv_obj_remove_style_all(_m_tap);
    lv_obj_set_size(_m_tap, 200, 200);
    lv_obj_set_style_radius(_m_tap, LV_RADIUS_CIRCLE, 0);
    lv_obj_center(_m_tap);
    lv_obj_add_flag(_m_tap, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(_m_tap, _centerTapCb, LV_EVENT_CLICKED, this);
    for (int i = 0; i < MAX_CHIPS; i++) {
        lv_obj_t* c = lv_obj_create(_g_menu);
        lv_obj_remove_style_all(c);
        lv_obj_set_size(c, CHIP_D, CHIP_D);
        lv_obj_set_style_radius(c, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_opa(c, LV_OPA_COVER, 0);
        lv_obj_remove_flag(c, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_add_flag(c, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_user_data(c, (void*)(intptr_t)i);
        lv_obj_add_event_cb(c, _chipTapCb, LV_EVENT_CLICKED, this);
        _chips[i] = c;
        _chip_sym[i] = label(c, &lv_font_montserrat_28, "");
        lv_obj_align(_chip_sym[i], LV_ALIGN_CENTER, 0, -10);
        _chip_lbl[i] = label(c, &lv_font_montserrat_14, "");
        lv_obj_align(_chip_lbl[i], LV_ALIGN_CENTER, 0, 22);
    }

    _restyle();
    _setMode(Mode::Searching);
}

// ------------------------------------------------------------------ theme
void KnobUI::applyTheme(const KnobTheme& t) {
    _t = t;
    _restyle();
}

void KnobUI::_restyle() {
    lv_obj_set_style_bg_color(_scr, _t.bg, 0);

    lv_obj_set_style_text_color(_s_title, _t.ink, 0);
    lv_obj_set_style_text_color(_s_status, _t.ink2, 0);
    lv_obj_set_style_arc_color(_s_spinner, _t.track, LV_PART_MAIN);
    lv_obj_set_style_arc_color(_s_spinner, _t.accent, LV_PART_INDICATOR);

    lv_obj_set_style_text_color(_p_title, _t.ink, 0);
    lv_obj_set_style_text_color(_p_hint, _t.ink2, 0);
    lv_obj_set_style_text_color(_p_help, _t.ink2, 0);
    lv_obj_set_style_text_color(_p_name, _t.ink2, 0);
    lv_obj_set_style_text_color(_p_status, _p_warn ? _t.accent : _t.ink, 0);
    for (int i = 0; i < 6; i++) {
        const bool act = i == _p_active;
        lv_obj_set_style_bg_color(_p_cells[i], _t.panel, 0);
        lv_obj_set_style_border_color(_p_cells[i], act ? _t.accent : _t.track, 0);
        lv_obj_set_style_border_width(_p_cells[i], act ? 4 : 2, 0);
        lv_obj_set_style_text_color(_p_digits[i], act ? _t.accent : _t.ink, 0);
    }

    lv_obj_set_style_arc_color(_vol_arc, _t.track, LV_PART_MAIN);
    lv_obj_set_style_arc_color(_vol_arc, _muted ? _t.accent_dim : _t.accent,
                               LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(_vol_arc, _muted ? _t.accent_dim : _t.accent,
                              LV_PART_KNOB);
    lv_obj_set_style_border_color(_vol_arc, _t.bg, LV_PART_KNOB);
    // No thumb until the boombox has told us its volume.
    const lv_opa_t knob_opa = _vol < 0 ? LV_OPA_TRANSP : LV_OPA_COVER;
    lv_obj_set_style_bg_opa(_vol_arc, knob_opa, LV_PART_KNOB);
    lv_obj_set_style_border_opa(_vol_arc, knob_opa, LV_PART_KNOB);
    lv_obj_set_style_arc_color(_prog_arc, _t.track, LV_PART_MAIN);
    lv_obj_set_style_arc_color(_prog_arc, _t.accent2, LV_PART_INDICATOR);
    lv_obj_set_style_text_color(_f_vol_label, _muted ? _t.accent : _t.ink2, 0);
    lv_obj_set_style_text_color(_f_source, _t.accent, 0);
    lv_obj_set_style_text_color(_f_title, _t.ink, 0);
    lv_obj_set_style_text_color(_f_artist, _t.ink2, 0);
    lv_obj_set_style_border_color(_f_glyph_ring, _t.accent, 0);
    lv_obj_set_style_text_color(_f_glyph, _t.accent, 0);

    lv_obj_set_style_text_color(_m_title, _t.ink, 0);
    lv_obj_set_style_text_color(_m_sub, _t.accent, 0);
    lv_obj_set_style_text_color(_m_hint, _t.ink2, 0);
    for (int i = 0; i < MAX_CHIPS; i++) _styleChip(i);
}

// ------------------------------------------------------------------ modes
void KnobUI::_setMode(Mode m) {
    _mode = m;
    show(_g_test, m == Mode::Test);
    show(_g_search, m == Mode::Searching);
    show(_g_pair, m == Mode::Pair);
    show(_g_face, m == Mode::Face);
    if (m != Mode::Face && _menu_open) closeMenu();
}

void KnobUI::showTest() { _setMode(Mode::Test); }

void KnobUI::showSearching(const char* title, const char* status) {
    setText(_s_title, title);
    setText(_s_status, status ? status : "");
    _setMode(Mode::Searching);
}

void KnobUI::setSearchingStatus(const char* status) { setText(_s_status, status); }

// ------------------------------------------------------------------- pair
void KnobUI::showPair(const String& name) {
    String n = name.length() ? String("Boombox: ") + name : String();
    setText(_p_name, n.c_str());
    _setMode(Mode::Pair);
}

void KnobUI::setPair(const uint8_t digits[6], int active, const char* status, bool warn) {
    char buf[2] = {0, 0};
    for (int i = 0; i < 6; i++) {
        buf[0] = (char)('0' + digits[i] % 10);
        setText(_p_digits[i], buf);
    }
    const bool restyle = active != _p_active || warn != _p_warn;
    _p_active = active;
    _p_warn = warn;
    setText(_p_status, status ? status : "");
    if (restyle) _restyle();
}

// ------------------------------------------------------------------- face
void KnobUI::showFace() { _setMode(Mode::Face); }

void KnobUI::_layoutTitle(const char* text) {
    // Two lines max with an ellipsis: LONG_DOT needs a fixed height, and a
    // single-line title should not reserve the second line.
    const lv_font_t* f = &lv_font_montserrat_32;
    const int32_t lh = lv_font_get_line_height(f);
    lv_point_t sz;
    // Measure the source string: in LONG_DOT mode the label's own buffer
    // already holds the dotted (truncated) text.
    lv_text_get_size(&sz, text, f, 0, 2, 330, LV_TEXT_FLAG_NONE);
    const int lines = sz.y > lh + 2 ? 2 : 1;
    lv_obj_set_height(_f_title, lines * lh + (lines - 1) * 2);
}

void KnobUI::setNowPlaying(const NowPlaying& np) {
    const bool first = !_np_valid;
    _np_valid = true;
    if (first || np.source_label != _np.source_label)
        setText(_f_source, np.source_label.c_str());
    if (first || np.has_track != _np.has_track || np.title != _np.title) {
        const char* t = np.has_track ? np.title.c_str() : "Nothing playing";
        _layoutTitle(t);
        lv_label_set_text(_f_title, t);
    }
    if (first || np.has_track != _np.has_track || np.artist != _np.artist) {
        setText(_f_artist, np.has_track ? np.artist.c_str() : "");
        show(_f_artist, np.has_track && np.artist.length());
    }
    show(_f_glyph_ring, np.has_track);
    if (first || np.playing != _np.playing)
        setText(_f_glyph, np.playing ? LV_SYMBOL_PAUSE : LV_SYMBOL_PLAY);

    int prog = -1;
    if (np.has_track && np.duration_s > 0) {
        uint32_t p = np.position_s > np.duration_s ? np.duration_s : np.position_s;
        prog = (int)(p * 1000ULL / np.duration_s);
    }
    if (prog != _prog) {
        _prog = prog;
        show(_prog_arc, prog >= 0 && !_menu_open);
        if (prog >= 0) lv_arc_set_value(_prog_arc, prog);
    }
    _np = np;
}

void KnobUI::setVolume(int v, bool muted) {
    if (v == _vol && muted == _muted) return;
    const bool restyle = muted != _muted || (v < 0) != (_vol < 0);
    _vol = v;
    _muted = muted;
    lv_arc_set_value(_vol_arc, v < 0 ? 0 : (v > 100 ? 100 : v));
    char buf[24];
    if (muted) snprintf(buf, sizeof buf, "MUTED");
    else if (v < 0) snprintf(buf, sizeof buf, "--");
    else snprintf(buf, sizeof buf, "%d%%", v);
    setText(_f_vol_label, buf);
    if (restyle) _restyle();
}

// ------------------------------------------------------------------- menu
void KnobUI::_styleChip(int i) {
    const bool sel = i == _sel;
    const bool marked = i < _n_items && _items[i].marked;
    lv_obj_set_style_bg_color(_chips[i], sel ? _t.accent : _t.panel, 0);
    lv_obj_set_style_border_width(_chips[i], marked ? 4 : 2, 0);
    lv_obj_set_style_border_color(_chips[i],
        marked ? _t.accent2 : (sel ? _t.accent : _t.track), 0);
    lv_obj_set_style_text_color(_chip_sym[i], sel ? _t.on_accent : _t.ink, 0);
    lv_obj_set_style_text_color(_chip_lbl[i], sel ? _t.on_accent : _t.ink2, 0);
}

void KnobUI::setMenu(const MenuItem* items, int n, int selected,
                     const char* title, const char* sub) {
    if (n > MAX_CHIPS) n = MAX_CHIPS;
    const bool relayout = n != _n_items;
    _n_items = n;
    _sel = selected;
    for (int i = 0; i < MAX_CHIPS; i++) {
        show(_chips[i], i < n);
        if (i >= n) continue;
        _items[i] = items[i];
        setText(_chip_sym[i], items[i].symbol);
        setText(_chip_lbl[i], items[i].label);
        if (relayout) {
            // Odd counts start at 12 o'clock; even counts straddle it (first
            // chip just left of 12) so no chip sits at 6 o'clock over the hint.
            const float start = (n % 2) ? -90.0f : -90.0f - 180.0f / n;
            const float a = (start + 360.0f * i / n) * (float)M_PI / 180.0f;
            const int x = CX + (int)lroundf(CHIP_R * cosf(a)) - CHIP_D / 2;
            const int y = CX + (int)lroundf(CHIP_R * sinf(a)) - CHIP_D / 2;
            lv_obj_set_pos(_chips[i], x, y);
        }
        _styleChip(i);
    }
    setText(_m_title, title ? title : "");
    setText(_m_sub, sub ? sub : "");
}

void KnobUI::openMenu(const MenuItem* items, int n, int selected,
                      const char* title, const char* sub) {
    _n_items = -1;   // force chip layout
    setMenu(items, n, selected, title, sub);
    if (!_menu_open) {
        _menu_open = true;
        show(_f_center, false);
        show(_prog_arc, false);
        show(_f_vol_label, false);
        show(_g_menu, true);
    }
}

void KnobUI::setMenuHint(const char* hint) { setText(_m_hint, hint); }

void KnobUI::closeMenu() {
    if (!_menu_open) return;
    _menu_open = false;
    show(_g_menu, false);
    show(_f_center, true);
    show(_f_vol_label, true);
    show(_prog_arc, _prog >= 0);
}

// ----------------------------------------------------------------- events
void KnobUI::_centerTapCb(lv_event_t* e) {
    auto* self = static_cast<KnobUI*>(lv_event_get_user_data(e));
    if (self && self->onCenterTap) self->onCenterTap();
}

void KnobUI::_chipTapCb(lv_event_t* e) {
    auto* self = static_cast<KnobUI*>(lv_event_get_user_data(e));
    lv_obj_t* chip = static_cast<lv_obj_t*>(lv_event_get_target(e));
    const int i = (int)(intptr_t)lv_obj_get_user_data(chip);
    if (self && self->onMenuTap) self->onMenuTap(i);
}

}  // namespace knob
