// Single-screen LVGL UI for the boombox-remote CYD firmware.
// See SingleScreen.h for the rationale (avoid lv_screen_load post-BLE).

#include "SingleScreen.h"
#include "Theme.h"
#include "transport/BleClient.h"
#include <ArduinoJson.h>
#include <time.h>

namespace boombox::ui {

SingleScreen* gUI = nullptr;

static const char* KEYS[12] = {
    "1","2","3", "4","5","6", "7","8","9", "C","0","<",
};

SingleScreen::SingleScreen() { gUI = this; }

void SingleScreen::build() {
    _screen = lv_screen_active();
    theme::applyScreen(_screen);

    _grp_searching = lv_obj_create(_screen);
    lv_obj_set_size(_grp_searching, 240, 320);
    lv_obj_set_style_bg_color(_grp_searching, theme::BG_DARK, 0);
    lv_obj_set_style_border_width(_grp_searching, 0, 0);
    lv_obj_set_style_pad_all(_grp_searching, 0, 0);
    lv_obj_clear_flag(_grp_searching, LV_OBJ_FLAG_SCROLLABLE);

    _grp_pair = lv_obj_create(_screen);
    lv_obj_set_size(_grp_pair, 240, 320);
    lv_obj_set_style_bg_color(_grp_pair, theme::BG_DARK, 0);
    lv_obj_set_style_border_width(_grp_pair, 0, 0);
    lv_obj_set_style_pad_all(_grp_pair, 0, 0);
    lv_obj_clear_flag(_grp_pair, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(_grp_pair, LV_OBJ_FLAG_HIDDEN);

    _grp_playing = lv_obj_create(_screen);
    lv_obj_set_size(_grp_playing, 240, 320);
    lv_obj_set_style_bg_color(_grp_playing, theme::BG_DARK, 0);
    lv_obj_set_style_border_width(_grp_playing, 0, 0);
    lv_obj_set_style_pad_all(_grp_playing, 0, 0);
    lv_obj_clear_flag(_grp_playing, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(_grp_playing, LV_OBJ_FLAG_HIDDEN);

    _buildSearching();
    _buildPair();
    _buildPlaying();
}

void SingleScreen::_buildSearching() {
    _searching_title = lv_label_create(_grp_searching);
    lv_label_set_text(_searching_title, "Boombox Remote");
    lv_obj_set_style_text_font(_searching_title, &lv_font_montserrat_20, 0);
    lv_obj_set_style_text_color(_searching_title, theme::FG_TEXT, 0);
    lv_obj_align(_searching_title, LV_ALIGN_TOP_MID, 0, 24);

    _searching_status = lv_label_create(_grp_searching);
    lv_label_set_text(_searching_status, "Looking for a boombox…");
    lv_obj_set_style_text_color(_searching_status, theme::MUTED, 0);
    lv_obj_set_style_text_font(_searching_status, &lv_font_montserrat_14, 0);
    lv_obj_set_width(_searching_status, 220);
    lv_label_set_long_mode(_searching_status, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_align(_searching_status, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(_searching_status, LV_ALIGN_TOP_MID, 0, 70);

    _searching_spinner = lv_spinner_create(_grp_searching);
    lv_obj_set_size(_searching_spinner, 70, 70);
    lv_obj_align(_searching_spinner, LV_ALIGN_CENTER, 0, 30);
}

void SingleScreen::_buildPair() {
    _pair_title = lv_label_create(_grp_pair);
    lv_label_set_text(_pair_title, "Enter PIN");
    lv_obj_set_style_text_font(_pair_title, &lv_font_montserrat_20, 0);
    lv_obj_set_style_text_color(_pair_title, theme::FG_TEXT, 0);
    lv_obj_align(_pair_title, LV_ALIGN_TOP_MID, 0, 12);

    _pair_hint = lv_label_create(_grp_pair);
    lv_label_set_text(_pair_hint, "Shown on the boombox screen");
    lv_obj_set_style_text_color(_pair_hint, theme::MUTED, 0);
    lv_obj_set_style_text_font(_pair_hint, &lv_font_montserrat_14, 0);
    lv_obj_align(_pair_hint, LV_ALIGN_TOP_MID, 0, 40);

    _pair_pin = lv_label_create(_grp_pair);
    lv_label_set_text(_pair_pin, "------");
    lv_obj_set_style_text_font(_pair_pin, &lv_font_montserrat_28, 0);
    lv_obj_set_style_text_color(_pair_pin, theme::ACCENT, 0);
    lv_obj_align(_pair_pin, LV_ALIGN_TOP_MID, 0, 68);

    const int btn_w = 60, btn_h = 40, gap = 6;
    const int grid_w = 3 * btn_w + 2 * gap;
    const int x0 = (240 - grid_w) / 2;
    const int y0 = 116;
    for (int i = 0; i < 12; i++) {
        int row = i / 3, col = i % 3;
        lv_obj_t* btn = theme::makeButton(_grp_pair, KEYS[i], btn_w, btn_h);
        if (i == 9 || i == 11) {
            lv_obj_set_style_bg_color(btn, theme::BUTTON_BG, 0);
            lv_obj_set_style_bg_color(btn, theme::BUTTON_BG_PRESSED, LV_STATE_PRESSED);
            lv_obj_set_style_text_color(
                lv_obj_get_child(btn, 0), theme::FG_TEXT, 0);
        }
        lv_obj_set_pos(btn, x0 + col * (btn_w + gap),
                              y0 + row * (btn_h + gap));
        lv_obj_set_user_data(btn, (void*)KEYS[i]);
        lv_obj_add_event_cb(btn, _onKeyTramp, LV_EVENT_CLICKED, nullptr);
        _pair_buttons[i] = btn;
    }

    _pair_status = lv_label_create(_grp_pair);
    lv_label_set_text(_pair_status, "Connected over Bluetooth");
    lv_obj_set_style_text_color(_pair_status, theme::MUTED, 0);
    lv_obj_set_style_text_font(_pair_status, &lv_font_montserrat_14, 0);
    lv_obj_align(_pair_status, LV_ALIGN_BOTTOM_MID, 0, -8);
}

void SingleScreen::_buildPlaying() {
    _play_boombox = lv_label_create(_grp_playing);
    lv_label_set_text(_play_boombox, "—");
    lv_obj_set_style_text_font(_play_boombox, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_color(_play_boombox, theme::FG_TEXT, 0);
    lv_obj_align(_play_boombox, LV_ALIGN_TOP_LEFT, 12, 8);

    _play_status = lv_label_create(_grp_playing);
    lv_label_set_text(_play_status, LV_SYMBOL_BLUETOOTH);
    lv_obj_set_style_text_color(_play_status, theme::ACCENT, 0);
    lv_obj_align(_play_status, LV_ALIGN_TOP_RIGHT, -12, 10);

    _play_title = lv_label_create(_grp_playing);
    lv_label_set_text(_play_title, "Nothing playing");
    lv_obj_set_style_text_font(_play_title, &lv_font_montserrat_24, 0);
    lv_obj_set_style_text_color(_play_title, theme::FG_TEXT, 0);
    lv_obj_set_width(_play_title, 220);
    lv_label_set_long_mode(_play_title, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_align(_play_title, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(_play_title, LV_ALIGN_TOP_MID, 0, 60);

    _play_artist = lv_label_create(_grp_playing);
    lv_label_set_text(_play_artist, "");
    lv_obj_set_style_text_font(_play_artist, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_color(_play_artist, theme::MUTED, 0);
    lv_obj_set_width(_play_artist, 220);
    lv_label_set_long_mode(_play_artist, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_align(_play_artist, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(_play_artist, LV_ALIGN_TOP_MID, 0, 100);

    const int btn_w = 60, btn_h = 44, gap = 12;
    const int row_w = 3 * btn_w + 2 * gap;
    const int x0 = (240 - row_w) / 2;
    const int y_row = 168;

    _play_btn_prev = theme::makeButton(_grp_playing, LV_SYMBOL_PREV, btn_w, btn_h);
    lv_obj_set_pos(_play_btn_prev, x0, y_row);
    lv_obj_add_event_cb(_play_btn_prev, _onPrevTramp, LV_EVENT_CLICKED, nullptr);

    _play_btn_play = theme::makeButton(_grp_playing, LV_SYMBOL_PLAY, btn_w, btn_h);
    _play_btn_play_lbl = lv_obj_get_child(_play_btn_play, 0);
    lv_obj_set_pos(_play_btn_play, x0 + btn_w + gap, y_row);
    lv_obj_add_event_cb(_play_btn_play, _onPlayTramp, LV_EVENT_CLICKED, nullptr);

    _play_btn_next = theme::makeButton(_grp_playing, LV_SYMBOL_NEXT, btn_w, btn_h);
    lv_obj_set_pos(_play_btn_next, x0 + 2 * (btn_w + gap), y_row);
    lv_obj_add_event_cb(_play_btn_next, _onNextTramp, LV_EVENT_CLICKED, nullptr);

    // Volume — two big +/- buttons (more touch-friendly than a slider).
    lv_obj_t* vol_down = theme::makeButton(_grp_playing, "VOL -", 100, 40);
    lv_obj_set_style_bg_color(vol_down, theme::BUTTON_BG, 0);
    lv_obj_set_style_bg_color(vol_down, theme::BUTTON_BG_PRESSED, LV_STATE_PRESSED);
    lv_obj_set_style_text_color(lv_obj_get_child(vol_down, 0), theme::FG_TEXT, 0);
    lv_obj_align(vol_down, LV_ALIGN_BOTTOM_LEFT, 12, -16);
    // Tap = one step; hold (>400ms) repeats every 100ms — LVGL's
    // long-press-repeat fires the same trampoline so the Pi-side delta
    // handler walks the volume by 5% each tick.
    lv_obj_add_event_cb(vol_down, _onVolDownTramp, LV_EVENT_CLICKED, nullptr);
    lv_obj_add_event_cb(vol_down, _onVolDownTramp,
                         LV_EVENT_LONG_PRESSED_REPEAT, nullptr);

    lv_obj_t* vol_up = theme::makeButton(_grp_playing, "VOL +", 100, 40);
    lv_obj_set_style_bg_color(vol_up, theme::BUTTON_BG, 0);
    lv_obj_set_style_bg_color(vol_up, theme::BUTTON_BG_PRESSED, LV_STATE_PRESSED);
    lv_obj_set_style_text_color(lv_obj_get_child(vol_up, 0), theme::FG_TEXT, 0);
    lv_obj_align(vol_up, LV_ALIGN_BOTTOM_RIGHT, -12, -16);
    lv_obj_add_event_cb(vol_up, _onVolUpTramp, LV_EVENT_CLICKED, nullptr);
    lv_obj_add_event_cb(vol_up, _onVolUpTramp,
                         LV_EVENT_LONG_PRESSED_REPEAT, nullptr);
}

void SingleScreen::_setMode(Mode m) {
    _mode = m;
    lv_obj_add_flag(_grp_searching, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(_grp_pair,      LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(_grp_playing,   LV_OBJ_FLAG_HIDDEN);
    switch (m) {
        case Mode::Searching: lv_obj_remove_flag(_grp_searching, LV_OBJ_FLAG_HIDDEN); break;
        case Mode::Pair:      lv_obj_remove_flag(_grp_pair,      LV_OBJ_FLAG_HIDDEN); break;
        case Mode::Playing:   lv_obj_remove_flag(_grp_playing,   LV_OBJ_FLAG_HIDDEN); break;
    }
    lv_obj_invalidate(_screen);
}

void SingleScreen::showSearching(const char* msg) {
    if (msg) lv_label_set_text(_searching_status, msg);
    _setMode(Mode::Searching);
}

void SingleScreen::setSearchingStatus(const char* msg) {
    if (msg) lv_label_set_text(_searching_status, msg);
}

void SingleScreen::showPair(BleClient* ble, PairDoneCallback on_done) {
    _ble = ble;
    _pair_cb = std::move(on_done);
    _pin = "";
    lv_label_set_text(_pair_pin, "------");
    lv_label_set_text(_pair_status, "Connected over Bluetooth");
    lv_obj_set_style_text_color(_pair_status, theme::MUTED, 0);
    _setMode(Mode::Pair);
}

void SingleScreen::_onKey(char d) {
    if (_pair_pending) return;
    if (d == 'C') { _pin = ""; }
    else if (d == '<') { if (_pin.length()) _pin.remove(_pin.length() - 1); }
    else if (d >= '0' && d <= '9') {
        if (_pin.length() < 6) _pin += d;
    }
    String shown = _pin + String("------").substring(_pin.length());
    lv_label_set_text(_pair_pin, shown.c_str());
    if (_pin.length() == 6) _attemptPair();
}

void SingleScreen::_attemptPair() {
    lv_label_set_text(_pair_status, "Pairing…");
    lv_obj_set_style_text_color(_pair_status, theme::MUTED, 0);
    _pair_pending = true;
    _pair_deadline = millis() + 9000;

    _ble->requestPair(_pin,
        [this](bool ok, const String& token, const String& bid,
                const String& bname, const String& error) {
            _pair_pending = false;
            if (!ok) {
                lv_label_set_text(_pair_status,
                    error == "bad_pin" ? "Wrong PIN — try again"
                    : error == "no_active_pin" ? "PIN expired or not active"
                    : "Pairing failed");
                lv_obj_set_style_text_color(_pair_status, theme::WARN, 0);
                _pin = "";
                lv_label_set_text(_pair_pin, "------");
                return;
            }
            PairedBoombox pb;
            pb.id         = bid;
            pb.name       = bname;
            pb.auth_token = token;
            pb.paired_at  = (uint32_t)time(nullptr);
            PairedBoomboxStore::save(pb);
            Serial.printf("[pair] saved boombox=%s\n", bname.c_str());
            lv_label_set_text(_pair_status, "Paired!");
            lv_obj_set_style_text_color(_pair_status, theme::ACCENT, 0);
            if (_pair_cb) _pair_cb(pb);
        }, 8000);
}

void SingleScreen::tickPair(uint32_t now_ms) {
    if (_mode != Mode::Pair || !_pair_pending) return;
    if ((int32_t)(now_ms - _pair_deadline) > 0) {
        _pair_pending = false;
        lv_label_set_text(_pair_status, "No response — try again");
        lv_obj_set_style_text_color(_pair_status, theme::WARN, 0);
        _pin = "";
        lv_label_set_text(_pair_pin, "------");
    }
}

void SingleScreen::showPlaying(ActionDispatch* actions, const String& boombox_name) {
    _actions = actions;
    lv_label_set_text(_play_boombox, boombox_name.c_str());
    _setMode(Mode::Playing);
}

void SingleScreen::onStateUpdate(const BoomboxState& s) {
    if (_mode != Mode::Playing) return;
    if (s.boombox_name.length())
        lv_label_set_text(_play_boombox, s.boombox_name.c_str());
    lv_label_set_text(_play_title,
        s.track.valid() ? s.track.title.c_str() : "Nothing playing");
    String aa = s.track.artist;
    if (s.track.album.length()) {
        if (aa.length()) aa += " — ";
        aa += s.track.album;
    }
    lv_label_set_text(_play_artist, aa.c_str());
    if (_play_btn_play_lbl) {
        lv_label_set_text(_play_btn_play_lbl,
            s.playing ? LV_SYMBOL_PAUSE : LV_SYMBOL_PLAY);
    }
}

void SingleScreen::onConnectionChange(bool ok) {
    if (_play_status) {
        lv_label_set_text(_play_status,
            ok ? LV_SYMBOL_BLUETOOTH : LV_SYMBOL_WARNING);
        lv_obj_set_style_text_color(_play_status,
            ok ? theme::ACCENT : theme::WARN, 0);
    }
}

void SingleScreen::_onKeyTramp(lv_event_t* e) {
    if (!gUI) return;
    lv_obj_t* btn = static_cast<lv_obj_t*>(lv_event_get_target(e));
    const char* k = static_cast<const char*>(lv_obj_get_user_data(btn));
    if (!k || !*k) return;
    gUI->_onKey(k[0]);
}

void SingleScreen::_onPlayTramp(lv_event_t* /*e*/) {
    if (gUI && gUI->_actions) gUI->_actions->playPause();
}
void SingleScreen::_onPrevTramp(lv_event_t* /*e*/) {
    if (gUI && gUI->_actions) gUI->_actions->previous();
}
void SingleScreen::_onNextTramp(lv_event_t* /*e*/) {
    if (gUI && gUI->_actions) gUI->_actions->next();
}
void SingleScreen::_onVolTramp(lv_event_t* /*e*/) { /* unused */ }
void SingleScreen::_onVolDownTramp(lv_event_t* /*e*/) {
    if (gUI && gUI->_actions) gUI->_actions->volumeDown();
}
void SingleScreen::_onVolUpTramp(lv_event_t* /*e*/) {
    if (gUI && gUI->_actions) gUI->_actions->volumeUp();
}

} // namespace boombox::ui
