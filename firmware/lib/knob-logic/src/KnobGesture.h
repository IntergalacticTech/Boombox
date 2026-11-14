// Click / double-click / long-press recogniser for a single push switch.
//
// Pure logic (no Arduino deps) so it runs under `pio test -e native`.
// Feed debounced edges with press()/release() and call tick() regularly;
// each returns at most one gesture.
//
//   * Long press: fires once while still held, after `long_ms`. The release
//     that follows is swallowed.
//   * Double click: a second press that starts within `double_ms` of the
//     first release, released before `long_ms`.
//   * Click: a release with no second press within `double_ms`. With double
//     click disabled it fires immediately on release (no wait).
#pragma once
#include <stdint.h>

namespace knob {

enum class Gesture : uint8_t { None, Click, DoubleClick, LongPress };

const char* gestureName(Gesture g);

class GestureRecognizer {
public:
    explicit GestureRecognizer(uint32_t double_ms = 350, uint32_t long_ms = 600)
        : _double_ms(double_ms), _long_ms(long_ms) {}

    void setDoubleClickEnabled(bool on) { _double_enabled = on; }
    bool doubleClickEnabled() const { return _double_enabled; }

    Gesture press(uint32_t now);
    Gesture release(uint32_t now);
    Gesture tick(uint32_t now);

    // Drop any in-flight gesture (e.g. the press was used to wake the screen).
    void reset();
    bool held() const { return _down; }

private:
    uint32_t _double_ms;
    uint32_t _long_ms;
    bool _double_enabled = true;

    bool _down = false;
    bool _long_fired = false;
    bool _second = false;          // current press is the 2nd of a pair
    bool _pending_click = false;   // released once, waiting for a 2nd press
    uint32_t _pressed_at = 0;
    uint32_t _released_at = 0;
};

}  // namespace knob
