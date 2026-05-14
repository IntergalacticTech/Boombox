#include "WifiCreds.h"
#include <Preferences.h>

namespace boombox {

static constexpr const char* NS = "wifi";

bool WifiCreds::load(String& ssid_out, String& psk_out) {
    Preferences p;
    if (!p.begin(NS, /*readOnly=*/true)) return false;
    ssid_out = p.getString("ssid", "");
    psk_out  = p.getString("psk", "");
    p.end();
    return ssid_out.length() > 0;
}

bool WifiCreds::save(const String& ssid, const String& psk) {
    Preferences p;
    if (!p.begin(NS, /*readOnly=*/false)) return false;
    p.putString("ssid", ssid);
    p.putString("psk", psk);
    p.end();
    return true;
}

void WifiCreds::clear() {
    Preferences p;
    if (!p.begin(NS, /*readOnly=*/false)) return;
    p.clear();
    p.end();
}

} // namespace boombox
