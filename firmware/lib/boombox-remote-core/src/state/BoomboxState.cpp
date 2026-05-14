#include "BoomboxState.h"
#include <ArduinoJson.h>

namespace boombox {

bool parseStateJson(const String& body, BoomboxState& out) {
    JsonDocument doc;
    if (deserializeJson(doc, body)) return false;
    if (!doc["ok"].as<bool>()) return false;
    JsonObject data = doc["data"].as<JsonObject>();
    if (data.isNull()) return false;

    out.boombox_id   = data["boombox"]["id"].as<String>();
    out.boombox_name = data["boombox"]["name"].as<String>();
    out.source       = data["source"].as<String>();
    out.playing      = data["playing"].as<bool>();

    if (data["track"].is<JsonObject>()) {
        JsonObject t = data["track"].as<JsonObject>();
        out.track.title      = t["title"].as<String>();
        out.track.artist     = t["artist"].as<String>();
        out.track.album      = t["album"].as<String>();
        out.track.duration_s = t["duration_s"].as<uint32_t>();
        out.track.position_s = t["position_s"].as<uint32_t>();
    } else {
        out.track = TrackInfo();
    }

    out.art_hash = data["art_hash"].as<String>();
    out.art_url  = data["art_url"].as<String>();
    out.volume   = data["volume"].is<int>() ? data["volume"].as<int>() : -1;
    out.muted    = data["muted"].as<bool>();

    out.sources_available.clear();
    for (JsonVariant v : data["sources_available"].as<JsonArray>()) {
        out.sources_available.push_back(v.as<String>());
    }
    out.sleep_timer_s = data["sleep_timer_s"].is<int>()
                          ? data["sleep_timer_s"].as<int>() : -1;
    out.recording = data["recording"].as<bool>();
    out.mic_on    = data["mic_on"].as<bool>();
    return true;
}

} // namespace boombox
