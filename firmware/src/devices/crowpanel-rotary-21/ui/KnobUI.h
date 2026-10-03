// LVGL face for the round 480x480 knob.
//
// One persistent screen hosts every mode as a visibility group (same
// approach as the CYD profile — no lv_screen_load churn):
//   * Test      colour bars + ring (bring-up / `testscreen` command)
//   * Searching scanning / reconnecting, with a small spinner
//   * Pair      six PIN digit cells, entered with the knob
//   * Face      volume arc on the rim, progress ring, now-playing centre
//   * Menu      ring of chips around the rim, over the face's volume arc
//
// Setters only touch LVGL when a value actually changes, so an idle face
// doesn't re-render.
#pragma once
#include <Arduino.h>
#include <lvgl.h>
#include <functional>
#include "KnobTheme.h"

namespace knob {

// The face's text comes from knob::faceText (lib/knob-logic/FaceText.h).
struct NowPlaying {
    String source_label;     // e.g. "VIDEO"; "" hides it
    String title;            // headline
    String artist;           // second line; "" hides it
    String note;             // small extra line ("Playing: ..."); "" hides it
    bool transport = false;  // show the play/pause glyph
    bool playing = false;
    bool progress = false;   // show the progress ring (needs a duration)
    uint32_t duration_s = 0;
    uint32_t position_s = 0;
};

struct MenuItem {
    const char* symbol = "";
    const char* label = "";
    bool marked = false;     // e.g. the current source
};

class KnobUI {
public:
    static constexpr int MAX_CHIPS = 6;

    void build();
    void applyTheme(const KnobTheme& t);
    const KnobTheme& theme() const { return _t; }

    void showTest();

    void showSearching(const char* title, const char* status);
    void setSearchingStatus(const char* status);

    void showPair(const String& boombox_name);
    // digits: 6 values 0-9; active: cell being edited (6 = all entered).
    void setPair(const uint8_t digits[6], int active, const char* status, bool warn);

    void showFace();
    void setNowPlaying(const NowPlaying& np);
    void setVolume(int v, bool muted);

    void openMenu(const MenuItem* items, int n, int selected,
                  const char* title, const char* sub);
    void setMenu(const MenuItem* items, int n, int selected,
                 const char* title, const char* sub);
    void setMenuHint(const char* hint);
    void closeMenu();
    bool menuOpen() const { return _menu_open; }

    // Touch callbacks (fired from LVGL events on the loop task).
    std::function<void()> onCenterTap;
    std::function<void(int)> onMenuTap;

private:
    enum class Mode { Test, Searching, Pair, Face };
    void _setMode(Mode m);
    void _restyle();
    void _layoutTitle(const char* text);
    void _styleChip(int i);

    KnobTheme _t;
    Mode _mode = Mode::Searching;
    lv_obj_t* _scr = nullptr;

    // groups
    lv_obj_t* _g_test = nullptr;
    lv_obj_t* _g_search = nullptr;
    lv_obj_t* _g_pair = nullptr;
    lv_obj_t* _g_face = nullptr;
    lv_obj_t* _g_menu = nullptr;

    // searching
    lv_obj_t* _s_title = nullptr;
    lv_obj_t* _s_status = nullptr;
    lv_obj_t* _s_spinner = nullptr;

    // pair
    lv_obj_t* _p_title = nullptr;
    lv_obj_t* _p_hint = nullptr;
    lv_obj_t* _p_cells[6] = {};
    lv_obj_t* _p_digits[6] = {};
    lv_obj_t* _p_help = nullptr;
    lv_obj_t* _p_status = nullptr;
    lv_obj_t* _p_name = nullptr;
    int _p_active = 0;
    bool _p_warn = false;

    // face
    lv_obj_t* _vol_arc = nullptr;
    lv_obj_t* _prog_arc = nullptr;
    lv_obj_t* _f_center = nullptr;
    lv_obj_t* _f_col = nullptr;
    lv_obj_t* _f_source = nullptr;
    lv_obj_t* _f_title = nullptr;
    lv_obj_t* _f_artist = nullptr;
    lv_obj_t* _f_note = nullptr;
    lv_obj_t* _f_glyph_ring = nullptr;
    lv_obj_t* _f_glyph = nullptr;
    lv_obj_t* _f_vol_label = nullptr;
    lv_obj_t* _f_tap = nullptr;
    NowPlaying _np;
    bool _np_valid = false;
    int _vol = -2;
    bool _muted = false;
    int _prog = -1;

    // menu
    lv_obj_t* _chips[MAX_CHIPS] = {};
    lv_obj_t* _chip_sym[MAX_CHIPS] = {};
    lv_obj_t* _chip_lbl[MAX_CHIPS] = {};
    MenuItem _items[MAX_CHIPS];
    int _n_items = 0;
    int _sel = 0;
    lv_obj_t* _m_title = nullptr;
    lv_obj_t* _m_sub = nullptr;
    lv_obj_t* _m_hint = nullptr;
    lv_obj_t* _m_tap = nullptr;
    bool _menu_open = false;

    static void _centerTapCb(lv_event_t* e);
    static void _chipTapCb(lv_event_t* e);
};

}  // namespace knob
