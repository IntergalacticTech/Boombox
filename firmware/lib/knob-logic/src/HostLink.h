// Pure pieces of the knob's USB host link (see UsbHostLink in the knob
// profile): the serial line assembler shared with the debug console, the
// protocol-line test, the "is the host link live?" window and a JSON-number
// check for command values.
//
// Wire protocol (newline-terminated JSON, one object per line):
//   host → knob  {"t":"hello"}
//                {"t":"state","d":{…consolidated state…}}
//   knob → host  {"t":"hello","profile":"crowpanel-rotary-21","fw":"0.1.0"}
//                {"t":"cmd","action":"volume","value":0.42}
// A line whose first non-blank byte is '{' is protocol; anything else is a
// console command (host → knob) or a log line (knob → host).
//
// Pure logic, unit-tested natively.
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace knob {

// Collects bytes into '\n'/'\r'-terminated lines in a fixed buffer. A line
// longer than CAP is dropped whole (nothing of it is ever returned), so a
// truncated JSON object can't masquerade as a valid one.
class LineAssembler {
public:
    static constexpr size_t CAP = 2048;

    // Feeds one byte. Returns true when a complete, non-empty line is ready;
    // line()/length() then hold it until the next feed().
    bool feed(char c);
    const char* line() const { return _buf; }
    size_t length() const { return _len; }
    uint32_t dropped() const { return _dropped; }

private:
    char _buf[CAP + 1] = {0};
    size_t _len = 0;
    bool _ready = false;
    bool _overflow = false;
    uint32_t _dropped = 0;
};

// True when the first non-blank byte of `s` is '{'.
bool isProtocolLine(const char* s);

// "Did something arrive in the last `window_ms`?" — wrap-safe on millis().
class LinkWindow {
public:
    explicit LinkWindow(uint32_t window_ms) : _window(window_ms) {}
    void note(uint32_t now) { _last = now; _seen = true; }
    void reset() { _seen = false; }
    bool active(uint32_t now) const {
        return _seen && (uint32_t)(now - _last) < _window;
    }

private:
    uint32_t _window;
    uint32_t _last = 0;
    bool _seen = false;
};

// True when `s` is a complete JSON number (e.g. "0.42", "-3", "1e2"), so a
// command value can go out unquoted.
bool isJsonNumber(const char* s);

}  // namespace knob
