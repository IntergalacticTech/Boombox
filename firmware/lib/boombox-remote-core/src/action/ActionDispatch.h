#pragma once
#include <Arduino.h>
#include "../transport/HttpClient.h"

namespace boombox {

// Convenience wrapper over HttpClient::postCommand — one method per
// well-known action so UI code doesn't sprinkle action strings.
class ActionDispatch {
public:
    explicit ActionDispatch(HttpClient* http) : _http(http) {}

    bool playPause()  { return _http->postCommand("play_pause", nullptr); }
    bool next()       { return _http->postCommand("next",       nullptr); }
    bool previous()   { return _http->postCommand("previous",   nullptr); }
    bool stop()       { return _http->postCommand("stop",       nullptr); }
    bool shuffle()    { return _http->postCommand("shuffle",    nullptr); }
    bool mute()       { return _http->postCommand("mute",       nullptr); }

    bool volume(int v) {
        String s = String(v);
        return _http->postCommand("volume", &s);
    }
    bool source(const String& name) {
        return _http->postCommand("source", &name);
    }
    bool sleepTimer(int minutes) {
        String s = String(minutes);
        return _http->postCommand("sleep_timer", &s);
    }

    bool micToggle()    { return _http->postCommand("mic_karaoke", nullptr); }
    bool recordToggle() { return _http->postCommand("record",      nullptr); }
    bool skinCycle()    { return _http->postCommand("skin_cycle",  nullptr); }

private:
    HttpClient* _http;
};

} // namespace boombox
