#include "HttpClient.h"
#include <HTTPClient.h>
#include <ArduinoJson.h>

namespace boombox {

HttpClient::HttpClient(const String& host_with_port, const String& base_path,
                        const String& token)
    : _token(token) {
    _base = "http://" + host_with_port + base_path;
    if (!_base.endsWith("/")) _base += "/";
}

bool HttpClient::getState(BoomboxState& out) {
    HTTPClient http;
    http.begin(_base + "state");
    http.addHeader("Authorization", "Bearer " + _token);
    http.setTimeout(3000);
    int code = http.GET();
    if (code != 200) { http.end(); return false; }
    String body = http.getString();
    http.end();
    return parseStateJson(body, out);
}

bool HttpClient::postCommand(const String& action, const String* value_or_null) {
    HTTPClient http;
    http.begin(_base + "command");
    http.addHeader("Authorization", "Bearer " + _token);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(3000);

    JsonDocument req;
    req["action"] = action;
    if (value_or_null) req["value"] = *value_or_null;
    String body;
    serializeJson(req, body);

    int code = http.POST(body);
    http.end();
    return code >= 200 && code < 300;
}

size_t HttpClient::getArt(const String& hash, uint8_t* out_buf, size_t out_buf_max) {
    HTTPClient http;
    http.begin(_base + "art/" + hash + ".jpg");
    http.addHeader("Authorization", "Bearer " + _token);
    http.setTimeout(5000);
    int code = http.GET();
    if (code != 200) { http.end(); return 0; }
    WiFiClient* stream = http.getStreamPtr();
    size_t total = 0;
    while (http.connected() && total < out_buf_max) {
        size_t avail = stream->available();
        if (avail == 0) { delay(5); continue; }
        size_t to_read = avail;
        if (to_read > out_buf_max - total) to_read = out_buf_max - total;
        size_t read = stream->readBytes(out_buf + total, to_read);
        if (read == 0) break;
        total += read;
    }
    http.end();
    return total;
}

} // namespace boombox
