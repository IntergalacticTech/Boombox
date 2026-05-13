#include "WifiManager.h"
#include "../storage/WifiCreds.h"
#include <WiFi.h>

namespace boombox {

bool WifiManager::tryStored() {
    String ssid, psk;
    if (!WifiCreds::load(ssid, psk)) return false;
    return join(ssid, psk);
}

bool WifiManager::join(const String& ssid, const String& psk, uint32_t timeout_ms) {
    Serial.printf("[wifi] joining %s\n", ssid.c_str());
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), psk.c_str());
    uint32_t deadline = millis() + timeout_ms;
    while (WiFi.status() != WL_CONNECTED && millis() < deadline) {
        delay(250);
    }
    bool ok = WiFi.status() == WL_CONNECTED;
    if (ok) {
        Serial.printf("[wifi] joined, ip=%s rssi=%d\n",
                       WiFi.localIP().toString().c_str(), WiFi.RSSI());
        WifiCreds::save(ssid, psk);
    } else {
        Serial.printf("[wifi] join failed (status=%d)\n", WiFi.status());
    }
    return ok;
}

void WifiManager::disconnect() { WiFi.disconnect(true); }

bool WifiManager::isConnected() const {
    return WiFi.status() == WL_CONNECTED;
}

String WifiManager::localIp() const {
    return WiFi.localIP().toString();
}

int8_t WifiManager::signalRssi() const { return WiFi.RSSI(); }

std::vector<WifiScanResult> WifiManager::scan(uint32_t /*timeout_ms*/) {
    std::vector<WifiScanResult> out;
    int n = WiFi.scanNetworks(/*async=*/false, /*show_hidden=*/false);
    for (int i = 0; i < n; i++) {
        WifiScanResult r;
        r.ssid = WiFi.SSID(i);
        r.rssi = WiFi.RSSI(i);
        r.secured = WiFi.encryptionType(i) != WIFI_AUTH_OPEN;
        out.push_back(r);
    }
    WiFi.scanDelete();
    return out;
}

} // namespace boombox
