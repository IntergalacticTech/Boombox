#pragma once
#include <Arduino.h>

namespace boombox {

// One SSID + PSK pair persisted in NVS namespace "wifi". Phase 2 MVP
// stores only the most-recent successful join; future phases may keep a
// list keyed by SSID for roaming.
class WifiCreds {
public:
    static bool load(String& ssid_out, String& psk_out);
    static bool save(const String& ssid, const String& psk);
    static void clear();
};

} // namespace boombox
