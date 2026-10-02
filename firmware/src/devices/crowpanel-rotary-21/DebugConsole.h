// Line-oriented serial debug console.
//
// Nobody can watch the panel during development, so the firmware takes
// commands over the USB-Serial/JTAG port:
//
//   snap            stream an LVGL snapshot of the active screen:
//                     SNAP <w> <h> <bytes> RGB565
//                     <base64 lines…>
//                     SNAPEND
//   enc +N / enc -N inject encoder detents
//   click / dclick / long        inject knob-switch gestures
//   tap X Y         inject a touch tap
//   state {json}    inject a BoomboxState payload ({"ok":true,"data":{…}}
//                   or the bare data object)
//   help            list commands
//
// Profiles register handlers with consoleOn(); consolePoll() runs them on
// the Arduino loop task (LVGL-safe).
//
// The same port carries the USB host link (see UsbHostLink.h): a line whose
// first non-blank byte is '{' is a protocol message, never a command — it
// goes to the consoleOnProtocol() handler. Lines over 2 KB are dropped whole.
#pragma once
#include <Arduino.h>
#include <functional>

namespace knob {

using ConsoleHandler = std::function<void(const String& args)>;

void consoleBegin();
void consoleOn(const char* name, const char* help, ConsoleHandler handler);
void consolePoll();

// Receives every protocol ('{'-prefixed) line, NUL-terminated.
using ProtocolHandler = std::function<void(const char* line, size_t len)>;
void consoleOnProtocol(ProtocolHandler handler);

// Streams an LVGL snapshot of the active screen in the SNAP framing above.
void consoleSnapshot();

}  // namespace knob
