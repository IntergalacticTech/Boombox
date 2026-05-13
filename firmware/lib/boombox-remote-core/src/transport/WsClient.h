#pragma once
#include <Arduino.h>
#include <functional>
#include "../state/BoomboxState.h"

namespace boombox {

// WebSocket subscriber for /api/remote/ws — receives state pushes and
// fires the registered callback with a parsed BoomboxState.
class WsClient {
public:
    using StateCallback  = std::function<void(const BoomboxState&)>;
    using StatusCallback = std::function<void(bool connected)>;

    WsClient(const String& host_with_port, const String& token);
    ~WsClient();

    void onState(StateCallback cb)   { _on_state = cb; }
    void onStatus(StatusCallback cb) { _on_status = cb; }
    void connect();
    void poll();                  // call from the main loop
    void disconnect();
    bool isConnected() const;

private:
    String _url;
    String _token;
    void* _impl;                  // type-erased to keep the header light
    StateCallback _on_state;
    StatusCallback _on_status;
};

} // namespace boombox
