#include "KnobGesture.h"

namespace knob {

const char* gestureName(Gesture g) {
    switch (g) {
        case Gesture::Click:       return "click";
        case Gesture::DoubleClick: return "dclick";
        case Gesture::LongPress:   return "long";
        default:                   return "none";
    }
}

void GestureRecognizer::reset() {
    _down = false;
    _long_fired = false;
    _second = false;
    _pending_click = false;
}

Gesture GestureRecognizer::press(uint32_t now) {
    if (_down) return Gesture::None;
    _down = true;
    _long_fired = false;
    _pressed_at = now;
    _second = false;
    if (_pending_click) {
        _pending_click = false;
        if (now - _released_at <= _double_ms) {
            _second = true;
        } else {
            // tick() wasn't called in time; the earlier click is still owed.
            return Gesture::Click;
        }
    }
    return Gesture::None;
}

Gesture GestureRecognizer::release(uint32_t now) {
    if (!_down) return Gesture::None;
    _down = false;
    if (_long_fired) {
        _long_fired = false;
        _second = false;
        return Gesture::None;
    }
    if (now - _pressed_at >= _long_ms) {
        // Held past the threshold without a tick(): it was a long press.
        _second = false;
        return Gesture::LongPress;
    }
    if (_second) {
        _second = false;
        return Gesture::DoubleClick;
    }
    if (!_double_enabled) return Gesture::Click;
    _pending_click = true;
    _released_at = now;
    return Gesture::None;
}

Gesture GestureRecognizer::tick(uint32_t now) {
    if (_down && !_long_fired && now - _pressed_at >= _long_ms) {
        _long_fired = true;
        _second = false;
        return Gesture::LongPress;
    }
    if (_pending_click && !_down && now - _released_at > _double_ms) {
        _pending_click = false;
        return Gesture::Click;
    }
    return Gesture::None;
}

}  // namespace knob
