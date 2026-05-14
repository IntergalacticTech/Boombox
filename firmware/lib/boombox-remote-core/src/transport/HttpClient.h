#pragma once
#include <Arduino.h>
#include "../state/BoomboxState.h"

namespace boombox {

// Thin wrapper over ESP32 HTTPClient + ArduinoJson. Talks to the
// boombox-remote service over the LAN (nginx-proxied).
class HttpClient {
public:
    // host_with_port: e.g. "boombox.local:8090"
    // base_path:     e.g. "/api/remote/"
    // token:         bearer token from pairing
    HttpClient(const String& host_with_port, const String& base_path,
                const String& token);

    bool getState(BoomboxState& out);
    bool postCommand(const String& action, const String* value_or_null);

    // Reads up to out_buf_max bytes of the JPEG into out_buf. Returns the
    // number of bytes actually read, or 0 on failure.
    size_t getArt(const String& hash, uint8_t* out_buf, size_t out_buf_max);

private:
    String _base;
    String _token;
};

} // namespace boombox
