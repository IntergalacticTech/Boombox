#include "BoomboxState.h"
#include <ArduinoJson.h>

namespace boombox {

// JSON null (e.g. a track with no artist) must read as "", not "null".
static String str(JsonVariantConst v) {
    return v.is<const char*>() ? String(v.as<const char*>()) : String();
}

bool parseStateJson(const String& body, BoomboxState& out) {
    JsonDocument doc;
    if (deserializeJson(doc, body)) return false;
    if (!doc["ok"].as<bool>()) return false;
    return parseStateData(doc["data"], out);
}

bool parseStateData(JsonVariantConst dataVar, BoomboxState& out) {
    JsonObjectConst data = dataVar.as<JsonObjectConst>();
    if (data.isNull()) return false;

    out.boombox_id   = str(data["boombox"]["id"]);
    out.boombox_name = str(data["boombox"]["name"]);
    out.source       = str(data["source"]);
    out.playing      = data["playing"].as<bool>();

    if (data["track"].is<JsonObject>()) {
        JsonObjectConst t = data["track"].as<JsonObjectConst>();
        out.track.title      = str(t["title"]);
        out.track.artist     = str(t["artist"]);
        out.track.album      = str(t["album"]);
        out.track.duration_s = t["duration_s"].as<uint32_t>();
        out.track.position_s = t["position_s"].as<uint32_t>();
    } else {
        out.track = TrackInfo();
    }

    out.art_hash = str(data["art_hash"]);
    out.art_url  = str(data["art_url"]);
    // boombox-remote reports volume as PipeWire's 0..1 (float, up to 1.5
    // with boost); accept integer percents too.
    JsonVariantConst vol = data["volume"];
    if (vol.is<int>() && vol.as<int>() > 1) {
        out.volume = (int16_t)vol.as<int>();
    } else if (vol.is<float>()) {
        const float f = vol.as<float>();
        out.volume = (int16_t)(f <= 1.5f ? f * 100.0f + 0.5f : f + 0.5f);
    } else {
        out.volume = -1;
    }
    out.muted    = data["muted"].as<bool>();
    out.shuffle  = data["shuffle"].as<bool>();
    out.repeat   = str(data["repeat"]);
    out.skin     = str(data["skin"]);
    out.theme    = ThemeTokens();
    if (data["theme"].is<JsonObject>()) {
        JsonObjectConst th = data["theme"].as<JsonObjectConst>();
        auto tok = [&](const char* k) { return str(th[k]); };
        out.theme.bg      = tok("bg");
        out.theme.panel   = tok("panel");
        out.theme.ink     = tok("ink");
        out.theme.ink2    = tok("ink2");
        out.theme.accent  = tok("accent");
        out.theme.accent2 = tok("accent2");
        out.theme.rule    = tok("rule");
    }

    out.sources_available.clear();
    for (JsonVariantConst v : data["sources_available"].as<JsonArrayConst>()) {
        out.sources_available.push_back(v.as<String>());
    }
    out.sleep_timer_s = data["sleep_timer_s"].is<int>()
                          ? data["sleep_timer_s"].as<int>() : -1;
    out.recording = data["recording"].as<bool>();
    out.mic_on    = data["mic_on"].as<bool>();
    return true;
}

} // namespace boombox
