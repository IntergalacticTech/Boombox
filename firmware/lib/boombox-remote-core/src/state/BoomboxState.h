#pragma once
#include <Arduino.h>
#include <vector>

namespace boombox {

struct TrackInfo {
    String title;
    String artist;
    String album;
    uint32_t duration_s = 0;
    uint32_t position_s = 0;
    bool valid() const { return title.length() > 0; }
};

// Mirrors the JSON payload from GET /api/remote/state.
struct BoomboxState {
    String boombox_id;
    String boombox_name;
    String source;                // "mopidy" | "airplay" | "spotify" | "bluetooth" | "movies" | ""
    bool playing = false;
    TrackInfo track;
    String art_hash;
    String art_url;
    int8_t volume = -1;           // 0-100 or -1 if unknown
    bool muted = false;
    std::vector<String> sources_available;
    int32_t sleep_timer_s = -1;   // -1 if unset
    bool recording = false;
    bool mic_on = false;
};

// Parses the JSON body of /api/remote/state into `out`. Returns true on
// success, false on malformed input or {"ok": false}.
bool parseStateJson(const String& body, BoomboxState& out);

} // namespace boombox
