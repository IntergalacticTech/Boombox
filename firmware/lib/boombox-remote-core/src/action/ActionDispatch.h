#pragma once
#include <Arduino.h>
#include "../transport/HttpClient.h"
#include "../transport/BleClient.h"

namespace boombox {

// Convenience wrapper over either HttpClient::postCommand or
// BleClient::sendCommand. Phase 2 MVP uses BLE exclusively; HTTP is
// available for the WiFi-fallback path (Phase 4).
class ActionDispatch {
public:
    explicit ActionDispatch(HttpClient* http) : _http(http), _ble(nullptr) {}
    explicit ActionDispatch(BleClient* ble)   : _http(nullptr), _ble(ble) {}

    bool playPause()  { return _send("play_pause", nullptr); }
    bool next()       { return _send("next",       nullptr); }
    bool previous()   { return _send("previous",   nullptr); }
    bool stop()       { return _send("stop",       nullptr); }
    bool shuffle()    { return _send("shuffle",    nullptr); }
    bool mute()       { return _send("mute",       nullptr); }

    bool volume(int v) {
        String s = String(v);
        return _send("volume", &s);
    }
    bool volumeUp()   { return _send("volume_up",   nullptr); }
    bool volumeDown() { return _send("volume_down", nullptr); }
    bool source(const String& name) {
        return _send("source", &name);
    }
    bool sleepTimer(int minutes) {
        String s = String(minutes);
        return _send("sleep_timer", &s);
    }

    bool micToggle()    { return _send("mic_karaoke", nullptr); }
    bool recordToggle() { return _send("record",      nullptr); }
    bool skinCycle()    { return _send("skin_cycle",  nullptr); }

private:
    HttpClient* _http;
    BleClient*  _ble;

    bool _send(const String& action, const String* value_or_null) {
        if (_ble)  return _ble->sendCommand(action, value_or_null);
        if (_http) return _http->postCommand(action, value_or_null);
        return false;
    }
};

} // namespace boombox
