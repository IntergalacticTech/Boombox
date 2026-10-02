#include "UsbHostLink.h"

#include <ArduinoJson.h>

#include "DebugConsole.h"

namespace knob {

void UsbHostLink::begin(StateCallback on_state) {
    _on_state = std::move(on_state);
    consoleOnProtocol([this](const char* line, size_t len) {
        handleLine(line, len, millis());
    });
}

void UsbHostLink::_writeLine(const String& json) {
    // One write so the line can't be split by a log line from this task.
    String out = json;
    out += '\n';
    Serial.write(reinterpret_cast<const uint8_t*>(out.c_str()), out.length());
}

void UsbHostLink::handleLine(const char* line, size_t len, uint32_t now) {
    JsonDocument doc;
    if (deserializeJson(doc, line, len) || !doc.is<JsonObjectConst>()) {
        _bad++;
        Serial.printf("[usb] bad protocol line (%u bytes)\n", (unsigned)len);
        return;
    }
    const char* t = doc["t"] | "";
    if (strcmp(t, "hello") == 0) {
        JsonDocument reply;
        reply["t"] = "hello";
        reply["profile"] = PROFILE_ID;
        reply["fw"] = BOOMBOX_FW_VERSION;
        String s;
        serializeJson(reply, s);
        _writeLine(s);
        return;
    }
    if (strcmp(t, "state") == 0) {
        boombox::BoomboxState s;
        if (!boombox::parseStateData(doc["d"], s)) {
            _bad++;
            Serial.println("[usb] state: unparsable");
            return;
        }
        const bool was_active = _window.active(now);
        _window.note(now);
        _states++;
        if (!was_active)
            Serial.printf("[usb] host state arriving (%u bytes, title='%s')\n",
                          (unsigned)len, s.track.title.c_str());
        if (_on_state) _on_state(s);
        return;
    }
    // Unknown types are ignored so the host can grow the protocol.
}

bool UsbHostLink::sendCommand(const char* action, const String* value, uint32_t now) {
    if (!active(now)) return false;
    // Built by hand so a numeric value goes out as a JSON number (what the
    // host expects for volume/seek), anything else as a string.
    JsonDocument doc;
    doc["t"] = "cmd";
    doc["action"] = action;
    if (value) {
        if (isJsonNumber(value->c_str())) doc["value"] = serialized(*value);
        else doc["value"] = *value;
    }
    String s;
    serializeJson(doc, s);
    _writeLine(s);
    _cmds++;
    return true;
}

}  // namespace knob
