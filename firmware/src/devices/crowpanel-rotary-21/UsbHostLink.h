// USB host link — the knob's wired connection to the boombox it is plugged
// into (services/knob_usb.py on the Pi).
//
// It shares the USB-Serial/JTAG port with the debug console and the log:
// the console hands over every line starting with '{' (consoleOnProtocol),
// and replies/commands go out as single '{'-prefixed lines that the host
// picks out of the log. Protocol (see HostLink.h for the framing):
//   host → knob  {"t":"hello"}            → {"t":"hello","profile":…,"fw":…}
//                {"t":"state","d":{…}}    the consolidated state (BLE "data")
//   knob → host  {"t":"cmd","action":"volume","value":0.42}
//
// USB is the active link while a valid state arrived in the last
// ACTIVE_WINDOW_MS; main.cpp then pauses BLE and skips pairing (the physical
// cable is the trust boundary). When the host goes quiet the knob falls back
// to BLE.
//
// Everything runs on the Arduino loop task (via consolePoll()), so the state
// callback may touch LVGL.
#pragma once
#include <Arduino.h>
#include <functional>

#include "HostLink.h"
#include "state/BoomboxState.h"

namespace knob {

class UsbHostLink {
public:
    static constexpr uint32_t ACTIVE_WINDOW_MS = 12000;
    using StateCallback = std::function<void(const boombox::BoomboxState&)>;

    // Registers with the debug console; call after consoleBegin().
    void begin(StateCallback on_state);

    // Sends the hello line unprompted (at boot), so a host that is already
    // listening pushes state straight away.
    void announce();

    // One protocol line from the console.
    void handleLine(const char* line, size_t len, uint32_t now);

    bool active(uint32_t now) const { return _window.active(now); }

    // Writes {"t":"cmd",…} as one line. Returns false if the link is idle.
    bool sendCommand(const char* action, const String* value, uint32_t now);

    uint32_t statesReceived() const { return _states; }
    uint32_t badLines() const { return _bad; }
    uint32_t commandsSent() const { return _cmds; }

private:
    void _writeLine(const String& json);
    void _sendHello();

    StateCallback _on_state;
    LinkWindow _window{ACTIVE_WINDOW_MS};
    uint32_t _states = 0;
    uint32_t _bad = 0;
    uint32_t _cmds = 0;
};

}  // namespace knob
