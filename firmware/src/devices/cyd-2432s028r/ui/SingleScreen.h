#pragma once
#include <lvgl.h>
#include <functional>
#include "action/ActionDispatch.h"
#include "state/BoomboxState.h"
#include "storage/PairedBoombox.h"

namespace boombox::ui {

// One persistent LVGL screen that hosts THREE modes:
//   1. SEARCHING — "Looking for a boombox" + spinner
//   2. PAIR      — title + PIN display + keypad
//   3. PLAYING   — track + transport + volume
//
// All widgets are created up-front during build(). Mode transitions toggle
// visibility via lv_obj_add/remove_flag(LV_OBJ_FLAG_HIDDEN). This avoids
// the lv_screen_load path which fails to render post-BLE on this stack.
class SingleScreen {
public:
    enum class Mode { Searching, Pair, Playing };
    using PairDoneCallback = std::function<void(const PairedBoombox&)>;

    SingleScreen();
    void build();   // call once at startup

    // Searching mode
    void showSearching(const char* msg = "Looking for a boombox…");
    void setSearchingStatus(const char* msg);

    // Pair mode
    void showPair(class BleClient* ble, PairDoneCallback on_done);
    void tickPair(uint32_t now_ms);

    // Playing mode
    void showPlaying(ActionDispatch* actions, const String& boombox_name);
    void onStateUpdate(const BoomboxState& s);
    void onConnectionChange(bool ok);

private:
    Mode _mode = Mode::Searching;
    lv_obj_t* _screen = nullptr;

    // SEARCHING widgets
    lv_obj_t* _grp_searching = nullptr;
    lv_obj_t* _searching_title = nullptr;
    lv_obj_t* _searching_status = nullptr;
    lv_obj_t* _searching_spinner = nullptr;

    // PAIR widgets
    lv_obj_t* _grp_pair = nullptr;
    lv_obj_t* _pair_title = nullptr;
    lv_obj_t* _pair_hint = nullptr;
    lv_obj_t* _pair_pin = nullptr;
    lv_obj_t* _pair_status = nullptr;
    lv_obj_t* _pair_buttons[12] = {nullptr};
    String _pin;
    class BleClient* _ble = nullptr;
    PairDoneCallback _pair_cb;
    bool _pair_pending = false;
    uint32_t _pair_deadline = 0;

    // PLAYING widgets
    lv_obj_t* _grp_playing = nullptr;
    lv_obj_t* _play_boombox = nullptr;
    lv_obj_t* _play_status = nullptr;
    lv_obj_t* _play_title = nullptr;
    lv_obj_t* _play_artist = nullptr;
    lv_obj_t* _play_btn_play = nullptr;
    lv_obj_t* _play_btn_play_lbl = nullptr;
    lv_obj_t* _play_btn_prev = nullptr;
    lv_obj_t* _play_btn_next = nullptr;
    lv_obj_t* _play_vol = nullptr;
    bool _play_vol_dragging = false;
    ActionDispatch* _actions = nullptr;

    void _setMode(Mode m);
    void _buildSearching();
    void _buildPair();
    void _buildPlaying();
    void _onKey(char d);
    void _attemptPair();

    static void _onKeyTramp(lv_event_t* e);
    static void _onPlayTramp(lv_event_t* e);
    static void _onPrevTramp(lv_event_t* e);
    static void _onNextTramp(lv_event_t* e);
    static void _onVolTramp(lv_event_t* e);
    static void _onVolDownTramp(lv_event_t* e);
    static void _onVolUpTramp(lv_event_t* e);
};

extern SingleScreen* gUI;   // file-scope singleton

} // namespace boombox::ui
