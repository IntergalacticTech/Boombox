// Knob controller: routes knob/touch input to the boombox, owns the face's
// modes (pairing, now playing, ring menu), theming and backlight power.
//
// Everything here runs on the Arduino loop task; LVGL is only touched from
// here and from KnobUI.
#pragma once
#include <Arduino.h>
#include <functional>

#include "KnobGesture.h"
#include "VolumeCoalescer.h"
#include "state/BoomboxState.h"
#include "ui/KnobUI.h"

namespace knob {

class KnobApp {
public:
    // Sends one command to the boombox; value may be null. Returns false if
    // the link is down.
    using Sender = std::function<bool(const char* action, const String* value)>;
    using PinCallback = std::function<void(const String& pin)>;

    void begin(Sender sender);
    KnobUI& ui() { return _ui; }

    // ---- mode changes driven by the BLE state machine
    void showTest();
    void showSearching(const char* title, const char* status);
    void setSearchingStatus(const char* status);
    void startPairing(const String& boombox_name, PinCallback on_pin);
    void pairFailed(const char* message);
    void pairSucceeded();
    void showFace();

    // ---- inputs (already debounced)
    void onDetents(int32_t detents, uint32_t now);
    void onButton(bool down, uint32_t now);
    void onGesture(Gesture g, uint32_t now);   // also used for injection
    bool onTouchDown(int16_t x, int16_t y, uint32_t now);   // false = swallow

    // ---- boombox state push (parsed)
    void onState(const boombox::BoomboxState& s, uint32_t now);

    // ---- periodic: gestures, coalesced volume sends, menu timeout, power
    void tick(uint32_t now);

    // Wake the backlight / reset the idle timer without acting on anything.
    void wake(uint32_t now) { _wakeIfAsleep(now); }

    // Power state, for diagnostics.
    const char* powerName() const;

private:
    enum class Mode { Test, Searching, Pair, Face };
    enum class Menu { None, Main, Source };
    enum class Power { Awake, Dim, Off };

    // input helpers
    bool _wakeIfAsleep(uint32_t now);
    void _activity(uint32_t now);
    void _setPower(Power p);

    // face
    void _refreshFace(uint32_t now);
    void _refreshVolume(uint32_t now);
    void _send(const char* action, const String* value = nullptr);
    void _seedOptimistic(uint32_t now);

    // menu
    void _openMenu(Menu m, int sel, uint32_t now);
    void _refreshMenu();
    void _menuRotate(int d, uint32_t now);
    void _menuChoose(int idx, uint32_t now);
    void _menuBack(uint32_t now);
    void _closeMenu();

    // pair
    void _refreshPair(const char* status, bool warn);

    KnobUI _ui;
    Sender _sender;
    Mode _mode = Mode::Searching;
    GestureRecognizer _gesture{350, 600};
    VolumeCoalescer _vol{125, 1000};
    uint32_t _last_vol_detent = 0;   // for turn-speed acceleration

    boombox::BoomboxState _state;
    bool _have_state = false;
    boombox::ThemeTokens _theme_tokens;
    bool _theme_applied = false;

    // Optimistic toggles hold until the boombox has had time to apply them.
    uint32_t _hold_until = 0;
    bool _opt_shuffle = false, _opt_muted = false, _opt_playing = false;
    String _opt_repeat;

    Menu _menu = Menu::None;
    int _menu_sel = 0;
    uint32_t _menu_last = 0;

    uint8_t _pin[6] = {0, 0, 0, 0, 0, 0};
    int _pin_active = 0;
    bool _pin_submitting = false;
    PinCallback _on_pin;

    Power _power = Power::Awake;
    uint32_t _last_activity = 0;
    bool _swallow_release = false;
};

}  // namespace knob
