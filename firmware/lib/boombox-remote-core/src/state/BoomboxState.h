#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
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

// Skin colour tokens as CSS strings (hex or rgba()), exactly as the kiosk
// publishes them. Empty when the boombox sent no theme.
struct ThemeTokens {
    String bg, panel, ink, ink2, accent, accent2, rule;
    bool present() const { return bg.length() || ink.length() || accent.length(); }
    bool operator==(const ThemeTokens& o) const {
        return bg == o.bg && panel == o.panel && ink == o.ink && ink2 == o.ink2
            && accent == o.accent && accent2 == o.accent2 && rule == o.rule;
    }
    bool operator!=(const ThemeTokens& o) const { return !(*this == o); }
};

// Mirrors the JSON payload from GET /api/remote/state.
struct BoomboxState {
    String boombox_id;
    String boombox_name;
    String source;                // "mopidy" | "airplay" | "spotify" | "bluetooth" | "movies" | ""
    bool playing = false;
    // boombox-state's power state ("power": "awake" | "asleep"). Absent or
    // anything else reads as awake.
    bool asleep = false;
    TrackInfo track;
    String art_hash;
    String art_url;
    // 0-100 (up to 150 with boost) or -1 if unknown. The boombox reports a
    // 0..1 float; integers > 1 are taken as percent.
    int16_t volume = -1;
    bool muted = false;
    bool shuffle = false;
    String repeat;                // "off" | "all" | "one" | "" (unknown)
    String skin;                  // active kiosk skin id
    ThemeTokens theme;
    std::vector<String> sources_available;
    int32_t sleep_timer_s = -1;   // -1 if unset
    bool recording = false;
    bool mic_on = false;
};

// Parses the JSON body of /api/remote/state into `out`. Returns true on
// success, false on malformed input or {"ok": false}.
bool parseStateJson(const String& body, BoomboxState& out);

// Same, from the already-parsed `data` object (the USB host link carries it
// as {"t":"state","d":{…}}).
bool parseStateData(JsonVariantConst data, BoomboxState& out);

} // namespace boombox
