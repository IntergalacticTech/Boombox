#pragma once
#include <Arduino.h>
#include <functional>
#include <vector>
#include "../state/BoomboxState.h"

namespace boombox {

struct BleScanResult {
    String name;
    String address;
    int8_t rssi;
};

// NimBLE-based central client for the boombox-remote BLE service.
//
// Lifecycle:
//   1. scan() — list available boomboxes (by their custom service UUID).
//   2. connect(address) — open a GATT connection.
//   3. requestPair(pin, onResult) — write PIN, await pair_response notify,
//      callback fires with {ok, auth_token, name, id} or {ok:false, error}.
//   4. subscribeState(cb) — fires on every state notify.
//   5. sendCommand(action, value?) — write to the command characteristic.
//
// The "auth_token" returned by requestPair is reserved for an eventual
// WiFi fallback; commands over BLE go through the connection itself
// (no per-call auth) since BLE proximity acts as the trust gate for MVP.
class BleClient {
public:
    using PairResult   = std::function<void(bool ok, const String& token,
                                              const String& boombox_id,
                                              const String& boombox_name,
                                              const String& error)>;
    using StateCallback = std::function<void(const BoomboxState&)>;
    using StatusCallback = std::function<void(bool connected)>;

    BleClient();

    std::vector<BleScanResult> scan(uint32_t duration_s = 5);
    bool connect(const String& address);
    // Non-blocking scan that ticks LVGL during the wait. Returns the
    // address of the first boombox seen, or empty string on timeout.
    // Designed to be called from the main loop without freezing the UI.
    String findFirstBoomboxNonBlocking(uint32_t duration_ms = 6000);
    void disconnect();
    bool isConnected() const;

    // Issues a PIN write + awaits pair_response. Blocks up to timeout_ms.
    void requestPair(const String& pin, PairResult cb,
                      uint32_t timeout_ms = 8000);

    // Register callbacks before subscribing.
    void onState(StateCallback cb)   { _on_state = cb; }
    void onStatus(StatusCallback cb) { _on_status = cb; }

    // Begin receiving state notifications. Must be connected.
    bool subscribeState();

    // Dispatch a command. Returns false if not connected.
    bool sendCommand(const String& action, const String* value_or_null);

private:
    void* _client = nullptr;          // NimBLEClient*, type-erased
    void* _svc = nullptr;             // NimBLERemoteService*
    void* _state_char = nullptr;      // NimBLERemoteCharacteristic*
    void* _command_char = nullptr;
    void* _pair_req_char = nullptr;
    void* _pair_resp_char = nullptr;
    StateCallback _on_state;
    StatusCallback _on_status;
    PairResult _pair_cb;
    bool _pair_pending = false;
    uint32_t _pair_deadline = 0;

    static void _stateNotifyTrampoline(void* /*characteristic*/, uint8_t* data,
                                         size_t length, bool notify);
    static void _pairNotifyTrampoline(void* /*characteristic*/, uint8_t* data,
                                        size_t length, bool notify);
};

} // namespace boombox
