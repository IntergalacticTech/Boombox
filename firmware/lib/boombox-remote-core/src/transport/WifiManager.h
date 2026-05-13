#pragma once
#include <Arduino.h>
#include <vector>

namespace boombox {

struct WifiScanResult {
    String ssid;
    int8_t rssi;
    bool secured;
};

class WifiManager {
public:
    // Try the SSID+PSK in NVS. Returns true on connect.
    bool tryStored();
    // Join a specific network; on success, persist to NVS.
    bool join(const String& ssid, const String& psk, uint32_t timeout_ms = 15000);
    void disconnect();
    bool isConnected() const;
    String localIp() const;
    int8_t signalRssi() const;
    std::vector<WifiScanResult> scan(uint32_t timeout_ms = 5000);
};

} // namespace boombox
