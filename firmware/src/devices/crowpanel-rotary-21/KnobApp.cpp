#include "KnobApp.h"
#include "board/Board.h"
#include "TextFold.h"

namespace knob {

namespace {

constexpr int VOLUME_STEP = 2;            // percent per detent
constexpr uint32_t MENU_IDLE_MS = 5000;
constexpr uint32_t DIM_AFTER_MS = 30000;
constexpr uint32_t OFF_AFTER_MS = 120000;
constexpr uint32_t OPTIMISTIC_HOLD_MS = 1500;
constexpr uint8_t BL_AWAKE = 204;
constexpr uint8_t BL_DIM = 28;

struct SourceDef {
    const char* id;       // as reported in state.source
    const char* command;  // value for the `source` action
    const char* label;    // face label
    const char* name;     // menu chip
    const char* symbol;
};
const SourceDef SOURCES[] = {
    {"mopidy", "library", "LIBRARY", "Library", LV_SYMBOL_LIST},
    {"airplay", "airplay", "AIRPLAY", "AirPlay", LV_SYMBOL_WIFI},
    {"spotify", "spotify", "SPOTIFY", "Spotify", LV_SYMBOL_AUDIO},
    {"bluetooth", "bluetooth", "BLUETOOTH", "Bluetooth", LV_SYMBOL_BLUETOOTH},
    {"movies", "movies", "MOVIES", "Movies", LV_SYMBOL_VIDEO},
};
constexpr int N_SOURCES = sizeof(SOURCES) / sizeof(SOURCES[0]);

int sourceIndex(const String& id) {
    for (int i = 0; i < N_SOURCES; i++)
        if (id == SOURCES[i].id || id == SOURCES[i].command) return i;
    return -1;
}

enum MainItem { M_PREV, M_NEXT, M_SOURCE, M_SHUFFLE, M_REPEAT, M_MUTE, M_COUNT };

const char* repeatLabel(const String& r) {
    if (r == "all") return "All";
    if (r == "one") return "One";
    return "Off";
}

String nextRepeat(const String& r) {
    if (r == "all") return "one";
    if (r == "one") return "off";
    return "all";
}

}  // namespace

// ------------------------------------------------------------------ setup
void KnobApp::begin(Sender sender) {
    _sender = std::move(sender);
    _ui.build();
    _ui.onCenterTap = [this]() {
        const uint32_t now = millis();
        if (_mode != Mode::Face) return;
        if (_menu != Menu::None) {
            _menuBack(now);
        } else {
            onGesture(Gesture::Click, now);
        }
    };
    _ui.onMenuTap = [this](int i) {
        const uint32_t now = millis();
        if (_menu == Menu::None) return;
        _menu_sel = i;
        _menuChoose(i, now);
    };
    _last_activity = millis();
    _setPower(Power::Awake);
}

// ------------------------------------------------------------------ modes
void KnobApp::showTest() {
    _closeMenu();
    _mode = Mode::Test;
    _ui.showTest();
}

void KnobApp::showSearching(const char* title, const char* status) {
    _closeMenu();
    _mode = Mode::Searching;
    _ui.showSearching(title, status);
}

void KnobApp::setSearchingStatus(const char* status) { _ui.setSearchingStatus(status); }

void KnobApp::startPairing(const String& name, PinCallback on_pin) {
    _closeMenu();
    _mode = Mode::Pair;
    _on_pin = std::move(on_pin);
    memset(_pin, 0, sizeof _pin);
    _pin_active = 0;
    _pin_submitting = false;
    _gesture.reset();
    _gesture.setDoubleClickEnabled(false);
    _ui.showPair(String(foldToAscii(name.c_str()).c_str()));
    _refreshPair("", false);
}

void KnobApp::pairFailed(const char* message) {
    _pin_submitting = false;
    _pin_active = 0;
    _refreshPair(message, true);
}

void KnobApp::pairSucceeded() {
    _pin_submitting = false;
    _refreshPair("Paired!", false);
}

void KnobApp::showFace() {
    _mode = Mode::Face;
    _gesture.reset();
    _gesture.setDoubleClickEnabled(true);
    _ui.showFace();
    _refreshFace(millis());
}

// ------------------------------------------------------------------ power
void KnobApp::_setPower(Power p) {
    _power = p;
    setBacklight(p == Power::Awake ? BL_AWAKE : p == Power::Dim ? BL_DIM : 0);
    Serial.printf("[power] %s\n", powerName());
}

const char* KnobApp::powerName() const {
    return _power == Power::Awake ? "awake" : _power == Power::Dim ? "dim" : "off";
}

void KnobApp::_activity(uint32_t now) { _last_activity = now; }

// Returns true if the input only woke the screen and must not be acted on.
bool KnobApp::_wakeIfAsleep(uint32_t now) {
    _activity(now);
    if (_power == Power::Awake) return false;
    _setPower(Power::Awake);
    return true;
}

// ------------------------------------------------------------------ input
void KnobApp::onDetents(int32_t d, uint32_t now) {
    if (!d) return;
    if (_wakeIfAsleep(now)) {
        Serial.printf("[input] %+ld detents woke the screen (ignored)\n", (long)d);
        return;
    }
    switch (_mode) {
        case Mode::Pair:
            if (_pin_submitting || _pin_active >= 6) return;
            _pin[_pin_active] = (uint8_t)(((int)_pin[_pin_active] + (int)(d % 10) + 10) % 10);
            _refreshPair("", false);
            break;
        case Mode::Face:
            if (_menu != Menu::None) {
                _menuRotate((int)d, now);
            } else if (_vol.reportedValue() < 0) {
                // Never guess: turning from an unknown level would send a
                // value near 0 (or 100) and jump the real volume.
                Serial.println("[vol] boombox volume unknown - turn ignored");
            } else {
                const int v = _vol.turn((int)d, VOLUME_STEP, now);
                Serial.printf("[vol] turn %+ld -> %d\n", (long)d, v);
                _refreshVolume(now);
            }
            break;
        default:
            break;
    }
}

void KnobApp::onButton(bool down, uint32_t now) {
    if (down) {
        if (_wakeIfAsleep(now)) {
            _gesture.reset();
            _swallow_release = true;
            Serial.println("[input] press woke the screen (ignored)");
            return;
        }
        onGesture(_gesture.press(now), now);
    } else {
        _activity(now);
        if (_swallow_release) {
            _swallow_release = false;
            return;
        }
        onGesture(_gesture.release(now), now);
    }
}

bool KnobApp::onTouchDown(int16_t, int16_t, uint32_t now) {
    if (_wakeIfAsleep(now)) {
        Serial.println("[input] touch woke the screen (ignored)");
        return false;
    }
    if (_menu != Menu::None) _menu_last = now;
    return true;
}

void KnobApp::onGesture(Gesture g, uint32_t now) {
    if (g == Gesture::None) return;
    Serial.printf("[input] gesture %s\n", gestureName(g));
    // Injected gestures (serial console) bypass onButton, so they wake too.
    if (_power != Power::Awake) {
        _wakeIfAsleep(now);
        Serial.println("[input] gesture woke the screen (ignored)");
        return;
    }
    _activity(now);

    if (_mode == Mode::Pair) {
        if (_pin_submitting) return;
        if (g == Gesture::LongPress) {
            if (_pin_active > 0) _pin_active--;
            _refreshPair("", false);
            return;
        }
        // Click (double click is disabled here; treat one as a click too).
        if (_pin_active < 6) _pin_active++;
        if (_pin_active >= 6) {
            String pin;
            for (int i = 0; i < 6; i++) pin += (char)('0' + _pin[i]);
            _pin_submitting = true;
            _refreshPair("Pairing...", false);
            if (_on_pin) _on_pin(pin);
        } else {
            _refreshPair("", false);
        }
        return;
    }

    if (_mode != Mode::Face) return;

    if (_menu != Menu::None) {
        if (g == Gesture::LongPress) _menuBack(now);
        else _menuChoose(_menu_sel, now);   // click or double click
        return;
    }

    switch (g) {
        case Gesture::Click:
            _send("play_pause");
            _seedOptimistic(now);
            _opt_playing = !_opt_playing;
            _hold_until = now + OPTIMISTIC_HOLD_MS;
            _refreshFace(now);
            break;
        case Gesture::DoubleClick:
            _send("next");
            break;
        case Gesture::LongPress:
            _openMenu(Menu::Main, M_PREV, now);
            break;
        default:
            break;
    }
}

// ------------------------------------------------------------------ state
void KnobApp::onState(const boombox::BoomboxState& s, uint32_t now) {
    _state = s;
    _have_state = true;
    _vol.reported(s.volume, now);

    if (!_theme_applied || s.theme != _theme_tokens) {
        _theme_tokens = s.theme;
        _theme_applied = true;
        _ui.applyTheme(s.theme.present() ? themeFromTokens(s.theme) : defaultTheme());
        Serial.printf("[theme] skin=%s accent=%s bg=%s\n", s.skin.c_str(),
                      s.theme.accent.c_str(), s.theme.bg.c_str());
    }
    if (_mode == Mode::Face) {
        _refreshFace(now);
        if (_menu != Menu::None) _refreshMenu();
    }
}

void KnobApp::_refreshFace(uint32_t now) {
    const bool hold = now < _hold_until;
    NowPlaying np;
    const int si = sourceIndex(_state.source);
    if (si >= 0) np.source_label = SOURCES[si].label;
    else if (_state.source.length()) { np.source_label = _state.source; np.source_label.toUpperCase(); }
    else np.source_label = _have_state ? "BOOMBOX" : "";
    np.has_track = _state.track.valid();
    // Built-in Montserrat is ASCII-only: fold accents/typographic punctuation.
    np.title = foldToAscii(_state.track.title.c_str()).c_str();
    np.artist = foldToAscii(_state.track.artist.c_str()).c_str();
    np.playing = hold ? _opt_playing : _state.playing;
    np.duration_s = _state.track.duration_s;
    np.position_s = _state.track.position_s;
    _ui.setNowPlaying(np);
    _refreshVolume(now);
}

void KnobApp::_refreshVolume(uint32_t now) {
    const bool hold = now < _hold_until;
    _ui.setVolume(_have_state || _vol.adjusting(now) ? _vol.displayed(now) : -1,
                  hold ? _opt_muted : _state.muted);
}

// Optimistic copies start from the boombox's truth unless a previous toggle
// is still being held.
void KnobApp::_seedOptimistic(uint32_t now) {
    if (now < _hold_until) return;
    _opt_playing = _state.playing;
    _opt_shuffle = _state.shuffle;
    _opt_muted = _state.muted;
    _opt_repeat = _state.repeat;
}

void KnobApp::_send(const char* action, const String* value) {
    const bool ok = _sender ? _sender(action, value) : false;
    Serial.printf("[cmd] %s%s%s%s\n", action, value ? " " : "",
                  value ? value->c_str() : "", ok ? "" : " (not sent: no link)");
}

// ------------------------------------------------------------------- menu
void KnobApp::_openMenu(Menu m, int sel, uint32_t now) {
    const bool was_open = _menu != Menu::None;
    _menu = m;
    _menu_sel = sel;
    _menu_last = now;
    _gesture.reset();
    _gesture.setDoubleClickEnabled(false);
    MenuItem items[KnobUI::MAX_CHIPS];
    int n = 0;
    if (m == Menu::Main) {
        items[M_PREV] = {LV_SYMBOL_PREV, "Previous", false};
        items[M_NEXT] = {LV_SYMBOL_NEXT, "Next", false};
        items[M_SOURCE] = {LV_SYMBOL_HOME, "Source", false};
        items[M_SHUFFLE] = {LV_SYMBOL_SHUFFLE, "Shuffle", false};
        items[M_REPEAT] = {LV_SYMBOL_LOOP, "Repeat", false};
        items[M_MUTE] = {LV_SYMBOL_MUTE, "Mute", false};
        n = M_COUNT;
    } else {
        for (int i = 0; i < N_SOURCES; i++)
            items[i] = {SOURCES[i].symbol, SOURCES[i].name, false};
        n = N_SOURCES;
    }
    // Labels/marks are filled in by _refreshMenu.
    if (!was_open) Serial.println("[menu] open");
    _ui.openMenu(items, n, sel, "", "");
    _ui.setMenuHint(m == Menu::Main ? "hold to close" : "hold for back");
    _refreshMenu();
}

void KnobApp::_refreshMenu() {
    const uint32_t now = millis();
    const bool hold = now < _hold_until;
    const bool shuffle = hold ? _opt_shuffle : _state.shuffle;
    const bool muted = hold ? _opt_muted : _state.muted;
    const String repeat = hold ? _opt_repeat : _state.repeat;
    const int cur = sourceIndex(_state.source);

    MenuItem items[KnobUI::MAX_CHIPS];
    int n = 0;
    String title, sub;
    if (_menu == Menu::Main) {
        items[M_PREV] = {LV_SYMBOL_PREV, "Previous", false};
        items[M_NEXT] = {LV_SYMBOL_NEXT, "Next", false};
        items[M_SOURCE] = {LV_SYMBOL_HOME, "Source", false};
        // Chip captions stay short; the ring mark shows "on" and the centre
        // spells the state out.
        items[M_SHUFFLE] = {LV_SYMBOL_SHUFFLE, "Shuffle", shuffle};
        items[M_REPEAT] = {LV_SYMBOL_LOOP, repeat == "one" ? "Repeat 1" : "Repeat",
                           repeat == "all" || repeat == "one"};
        items[M_MUTE] = {muted ? LV_SYMBOL_MUTE : LV_SYMBOL_VOLUME_MAX,
                         muted ? "Unmute" : "Mute", muted};
        n = M_COUNT;
        switch (_menu_sel) {
            case M_PREV: title = "Previous"; sub = "previous track"; break;
            case M_NEXT: title = "Next"; sub = "next track"; break;
            case M_SOURCE:
                title = "Source";
                sub = cur >= 0 ? SOURCES[cur].name : "choose";
                break;
            case M_SHUFFLE: title = "Shuffle"; sub = shuffle ? "On" : "Off"; break;
            case M_REPEAT: title = "Repeat"; sub = repeatLabel(repeat); break;
            case M_MUTE: title = muted ? "Unmute" : "Mute"; sub = muted ? "Muted" : "Sound on"; break;
        }
    } else {
        for (int i = 0; i < N_SOURCES; i++)
            items[i] = {SOURCES[i].symbol, SOURCES[i].name, i == cur};
        n = N_SOURCES;
        title = SOURCES[_menu_sel].name;
        sub = _menu_sel == cur ? "current" : "switch to";
    }
    _ui.setMenu(items, n, _menu_sel, title.c_str(), sub.c_str());
}

void KnobApp::_menuRotate(int d, uint32_t now) {
    const int n = _menu == Menu::Main ? M_COUNT : N_SOURCES;
    _menu_sel = ((_menu_sel + d) % n + n) % n;
    _menu_last = now;
    _refreshMenu();
}

void KnobApp::_menuChoose(int idx, uint32_t now) {
    _menu_last = now;
    _seedOptimistic(now);
    if (_menu == Menu::Source) {
        if (idx < 0 || idx >= N_SOURCES) return;
        String v = SOURCES[idx].command;
        _send("source", &v);
        _closeMenu();
        return;
    }
    switch (idx) {
        case M_PREV: _send("previous"); _closeMenu(); return;
        case M_NEXT: _send("next"); _closeMenu(); return;
        case M_SOURCE: {
            const int cur = sourceIndex(_state.source);
            _openMenu(Menu::Source, cur >= 0 ? cur : 0, now);
            return;
        }
        case M_SHUFFLE:
            _send("shuffle");
            _opt_shuffle = !_opt_shuffle;
            break;
        case M_REPEAT:
            _send("repeat");
            _opt_repeat = nextRepeat(_opt_repeat);
            break;
        case M_MUTE:
            _send("mute");
            _opt_muted = !_opt_muted;
            break;
        default:
            return;
    }
    _hold_until = now + OPTIMISTIC_HOLD_MS;
    _refreshMenu();
    _refreshFace(now);
}

void KnobApp::_menuBack(uint32_t now) {
    if (_menu == Menu::Source) _openMenu(Menu::Main, M_SOURCE, now);
    else _closeMenu();
}

void KnobApp::_closeMenu() {
    if (_menu == Menu::None) return;
    _menu = Menu::None;
    _ui.closeMenu();
    _gesture.reset();
    _gesture.setDoubleClickEnabled(true);
    Serial.println("[menu] close");
}

void KnobApp::_refreshPair(const char* status, bool warn) {
    _ui.setPair(_pin, _pin_active, status, warn);
}

// ------------------------------------------------------------------- tick
void KnobApp::tick(uint32_t now) {
    onGesture(_gesture.tick(now), now);

    if (_mode == Mode::Face) {
        const int v = _vol.pollSend(now);
        if (v >= 0) {
            // The boombox takes 0..1 floats (values > 1 are read as percent,
            // so "1" would mean 100%, not 1%). Always send a fraction.
            String val = String(v / 100.0f, 2);
            _send("volume", &val);
        }
        _refreshVolume(now);   // settles the arc ~1 s after the last turn
        if (_hold_until && (int32_t)(now - _hold_until) >= 0) {
            _hold_until = 0;       // optimistic hold over: show the truth
            _refreshFace(now);
            if (_menu != Menu::None) _refreshMenu();
        }
        if (_menu != Menu::None && now - _menu_last > MENU_IDLE_MS) {
            Serial.println("[menu] idle timeout");
            _closeMenu();
        }
    }

    const uint32_t idle = now - _last_activity;
    if (_power == Power::Awake && idle > DIM_AFTER_MS) _setPower(Power::Dim);
    else if (_power == Power::Dim && idle > OFF_AFTER_MS) _setPower(Power::Off);
}

}  // namespace knob
