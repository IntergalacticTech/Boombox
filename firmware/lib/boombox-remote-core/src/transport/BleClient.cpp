// NimBLE-Arduino-backed central client for the boombox-remote BLE service.
// Mirrors the Pi-side ble_peripheral.py UUIDs and protocol.

#include "BleClient.h"
#include <NimBLEDevice.h>
#include <ArduinoJson.h>
#include <lvgl.h>

namespace boombox {

static const NimBLEUUID SERVICE_UUID("0000bbbb-0000-1000-8000-00805f9b34fb");
static const NimBLEUUID DEVICE_INFO_UUID("0000bbbe-0000-1000-8000-00805f9b34fb");
static const NimBLEUUID PAIR_REQUEST_UUID("0000bbb1-0000-1000-8000-00805f9b34fb");
static const NimBLEUUID PAIR_RESPONSE_UUID("0000bbb2-0000-1000-8000-00805f9b34fb");
static const NimBLEUUID STATE_UUID("0000bbb3-0000-1000-8000-00805f9b34fb");
static const NimBLEUUID COMMAND_UUID("0000bbb4-0000-1000-8000-00805f9b34fb");

// File-scope singleton so the static notify callbacks can reach the
// active instance. There's at most one BleClient at a time on the CYD.
static BleClient* g_inst = nullptr;

BleClient::BleClient() {
    g_inst = this;
    NimBLEDevice::init("boombox-cyd");
    NimBLEDevice::setPower(ESP_PWR_LVL_P9);
}

std::vector<BleScanResult> BleClient::scan(uint32_t duration_s) {
    std::vector<BleScanResult> out;
    NimBLEScan* scanner = NimBLEDevice::getScan();
    scanner->setActiveScan(true);
    scanner->setInterval(100);
    scanner->setWindow(99);
    NimBLEScanResults results = scanner->getResults(duration_s * 1000, false);
    int n = results.getCount();
    Serial.printf("[ble] scan: %d devices visible\n", n);
    for (int i = 0; i < n; i++) {
        const NimBLEAdvertisedDevice* d = results.getDevice(i);
        if (!d) continue;
        String name = String(d->getName().c_str());
        String addr = String(d->getAddress().toString().c_str());
        bool has_svc = d->isAdvertisingService(SERVICE_UUID);
        Serial.printf("  %s '%s' rssi=%d svc=%s\n",
                       addr.c_str(), name.c_str(), d->getRSSI(),
                       has_svc ? "yes" : "no");
        // Accept anything named "Boombox" too, in case the Pi advert
        // omits the service UUID from the limited adv-data payload.
        if (!has_svc && !name.equalsIgnoreCase("Boombox")) continue;
        BleScanResult r;
        r.name = name;
        r.address = addr;
        r.rssi = d->getRSSI();
        out.push_back(r);
    }
    scanner->clearResults();
    return out;
}

String BleClient::findFirstBoomboxNonBlocking(uint32_t duration_ms) {
    // Start an async NimBLE scan. Each adv fires the onResult callback,
    // which records a hit. The main loop polls + ticks LVGL.
    static String found_address;
    found_address = "";
    NimBLEScan* scanner = NimBLEDevice::getScan();
    scanner->setActiveScan(true);
    scanner->setInterval(100);
    scanner->setWindow(99);

    struct ScanCb : NimBLEScanCallbacks {
        void onResult(const NimBLEAdvertisedDevice* d) override {
            if (!d) return;
            const String name(d->getName().c_str());
            const bool has_svc = d->isAdvertisingService(SERVICE_UUID);
            if (has_svc || name.equalsIgnoreCase("Boombox")) {
                found_address = String(d->getAddress().toString().c_str());
                Serial.printf("[ble] async-scan hit '%s' %s\n",
                               name.c_str(), found_address.c_str());
                NimBLEDevice::getScan()->stop();
            }
        }
    };
    static ScanCb cb;
    scanner->setScanCallbacks(&cb, false);

    if (!scanner->start(duration_ms, false, true)) {
        Serial.println("[ble] async scan start failed");
        return "";
    }

    uint32_t deadline = millis() + duration_ms + 500;
    while (found_address.length() == 0 && millis() < deadline) {
        lv_timer_handler();
        delay(15);
    }
    scanner->stop();
    return found_address;
}

bool BleClient::connect(const String& address) {
    auto* client = NimBLEDevice::createClient();
    _client = client;
    client->setConnectTimeout(8 * 1000);
    NimBLEAddress addr(std::string(address.c_str()), BLE_ADDR_PUBLIC);
    if (!client->connect(addr, false)) {
        Serial.printf("[ble] connect failed to %s\n", address.c_str());
        NimBLEDevice::deleteClient(client);
        _client = nullptr;
        if (_on_status) _on_status(false);
        return false;
    }
    auto* svc = client->getService(SERVICE_UUID);
    if (!svc) {
        Serial.println("[ble] service not found on peer");
        client->disconnect();
        _client = nullptr;
        if (_on_status) _on_status(false);
        return false;
    }
    _svc            = svc;
    _state_char     = svc->getCharacteristic(STATE_UUID);
    _command_char   = svc->getCharacteristic(COMMAND_UUID);
    _pair_req_char  = svc->getCharacteristic(PAIR_REQUEST_UUID);
    _pair_resp_char = svc->getCharacteristic(PAIR_RESPONSE_UUID);
    Serial.println("[ble] connected; discovered chars");
    if (_on_status) _on_status(true);
    return true;
}

void BleClient::disconnect() {
    auto* c = static_cast<NimBLEClient*>(_client);
    if (c) {
        c->disconnect();
        NimBLEDevice::deleteClient(c);
    }
    _client = _svc = _state_char = _command_char = nullptr;
    _pair_req_char = _pair_resp_char = nullptr;
    if (_on_status) _on_status(false);
}

bool BleClient::isConnected() const {
    auto* c = static_cast<NimBLEClient*>(_client);
    return c && c->isConnected();
}

void BleClient::requestPair(const String& pin, PairResult cb,
                              uint32_t timeout_ms) {
    auto* resp = static_cast<NimBLERemoteCharacteristic*>(_pair_resp_char);
    auto* req  = static_cast<NimBLERemoteCharacteristic*>(_pair_req_char);
    if (!resp || !req) {
        cb(false, "", "", "", "service_chars_missing");
        return;
    }
    _pair_cb = cb;
    _pair_pending = true;
    _pair_deadline = millis() + timeout_ms;

    if (resp->canNotify()) {
        if (!resp->subscribe(true, _pairNotifyTrampoline)) {
            Serial.println("[ble] pair_response subscribe failed");
        }
    }
    std::string p(pin.c_str());
    if (!req->writeValue(p, false)) {
        Serial.println("[ble] pair_request write failed");
        _pair_pending = false;
        cb(false, "", "", "", "write_failed");
        return;
    }
    Serial.printf("[ble] sent pin=%s, awaiting pair_response…\n", pin.c_str());
    // Caller polls millis() vs _pair_deadline to time out if no notify.
}

bool BleClient::subscribeState() {
    auto* sc = static_cast<NimBLERemoteCharacteristic*>(_state_char);
    if (!sc) return false;
    if (!sc->canNotify()) {
        Serial.println("[ble] state char does not support notify");
        return false;
    }
    return sc->subscribe(true, _stateNotifyTrampoline);
}

bool BleClient::sendCommand(const String& action, const String* value_or_null) {
    auto* cc = static_cast<NimBLERemoteCharacteristic*>(_command_char);
    if (!cc) return false;
    JsonDocument doc;
    doc["action"] = action;
    if (value_or_null) doc["value"] = *value_or_null;
    String s;
    serializeJson(doc, s);
    return cc->writeValue(std::string(s.c_str()), false);
}

void BleClient::_stateNotifyTrampoline(void* /*chr*/, uint8_t* data,
                                          size_t length, bool /*notify*/) {
    if (!g_inst || !g_inst->_on_state) return;
    String body(reinterpret_cast<char*>(data), length);
    BoomboxState s;
    if (parseStateJson(body, s)) {
        g_inst->_on_state(s);
    }
}

void BleClient::_pairNotifyTrampoline(void* /*chr*/, uint8_t* data,
                                         size_t length, bool /*notify*/) {
    if (!g_inst || !g_inst->_pair_pending || !g_inst->_pair_cb) return;
    String body(reinterpret_cast<char*>(data), length);
    JsonDocument doc;
    if (deserializeJson(doc, body)) {
        g_inst->_pair_cb(false, "", "", "", "parse_error");
        g_inst->_pair_pending = false;
        return;
    }
    bool ok = doc["ok"].as<bool>();
    if (!ok) {
        String err = doc["error"].as<String>();
        g_inst->_pair_cb(false, "", "", "", err);
    } else {
        g_inst->_pair_cb(true,
            doc["auth_token"].as<String>(),
            doc["boombox_id"].as<String>(),
            doc["boombox_name"].as<String>(),
            "");
    }
    g_inst->_pair_pending = false;
}

} // namespace boombox
