#include "WsClient.h"
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>

namespace boombox {

using websockets::WebsocketsClient;

WsClient::WsClient(const String& host_with_port, const String& token)
    : _token(token) {
    _url  = "ws://" + host_with_port + "/api/remote/ws?token=" + token;
    _impl = new WebsocketsClient();
}

WsClient::~WsClient() {
    delete static_cast<WebsocketsClient*>(_impl);
}

void WsClient::connect() {
    auto* c = static_cast<WebsocketsClient*>(_impl);
    c->onMessage([this](websockets::WebsocketsMessage msg) {
        BoomboxState s;
        if (parseStateJson(msg.data(), s) && _on_state) _on_state(s);
    });
    c->onEvent([this](websockets::WebsocketsEvent event, String /*data*/) {
        if (event == websockets::WebsocketsEvent::ConnectionOpened) {
            if (_on_status) _on_status(true);
        } else if (event == websockets::WebsocketsEvent::ConnectionClosed) {
            if (_on_status) _on_status(false);
        }
    });
    if (!c->connect(_url)) {
        Serial.println("[ws] connect failed");
    }
}

void WsClient::poll() {
    static_cast<WebsocketsClient*>(_impl)->poll();
}

void WsClient::disconnect() {
    static_cast<WebsocketsClient*>(_impl)->close();
}

bool WsClient::isConnected() const {
    return static_cast<WebsocketsClient*>(_impl)->available();
}

} // namespace boombox
