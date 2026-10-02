// boombox-remote firmware — CrowPanel 2.1" rotary knob.
//
// A themed volume + transport knob for the boombox, over USB or BLE:
//   rotate = volume, click = play/pause, double click = next,
//   long press = ring menu (previous, next, source, shuffle, repeat, mute).
//
// Boot / link state machine (same shape as the CYD profile):
//   Scan → Connect → (saved pairing for this boombox? → Playing : Pair)
//   Pair: PIN entered with the knob → pair_request → Playing
//   Playing: state notifies drive the face; a dropped link goes back to Scan
//            and the face shows "Reconnecting…".
//
// USB host link (UsbHostLink.h): when the knob is plugged into the boombox
// and the host has sent a valid state in the last 12 s, USB is the active
// link — state comes from the host, commands go back over USB, BLE scanning
// and connecting stop and the pairing UI is skipped (the cable is the trust
// boundary). When the host goes quiet the state machine above resumes at
// Scan, so the knob still works cordless.
//
// All LVGL work happens on this (Arduino loop) task. BLE notifies are
// buffered by BleClient and drained in pumpEvents(); the pair response is
// handed over through a small mailbox for the same reason.
//
// Serial console (115200, USB-Serial/JTAG) — see DebugConsole.h. Extra
// commands here: state, demo, ble, usb, testscreen, unpair, reboot, info, bl.
// `state`/`demo`/`ble off` pause both links (demo mode) until `ble on`.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <lvgl.h>
#include <time.h>

#include "board/Board.h"
#include "board/LvglPort.h"
#include "DebugConsole.h"
#include "KnobApp.h"
#include "UsbHostLink.h"
#include "storage/PairedBoombox.h"
#include "transport/BleClient.h"
#include "state/BoomboxState.h"

using namespace knob;
using boombox::BleClient;
using boombox::BoomboxState;
using boombox::PairedBoombox;
using boombox::PairedBoomboxStore;

static KnobApp gApp;
static BleClient* gBle = nullptr;
static UsbHostLink gUsb;
static bool gUsbMode = false;   // USB is the active link (BLE idle)

enum class Link { Scan, Connect, Pair, Playing, Paused };
static Link gLink = Link::Scan;
static String gPendingAddress;
static PairedBoombox gPair;
static bool gHaveSaved = false;
static bool gPlayingWired = false;
static uint32_t gNextScanAt = 0;

// Pair response mailbox: written on the NimBLE host task, read in loop().
static portMUX_TYPE gPairMux = portMUX_INITIALIZER_UNLOCKED;
static volatile bool gPairDone = false;
static bool gPairOk = false;
static String gPairToken, gPairId, gPairName, gPairError;
static bool gPairPending = false;
static uint32_t gPairDeadline = 0;

// ------------------------------------------------------------------ input
static void pollInputs(uint32_t now) {
    const int32_t d = encoderTakeDetents();
    if (d) {
        Serial.printf("[enc] detents=%+ld raw=%ld\n", (long)d, (long)encoderRawCount());
        gApp.onDetents(d, now);
    }
    bool down;
    if (buttonPoll(now, down)) {
        Serial.printf("[btn] %s\n", down ? "press" : "release");
        gApp.onButton(down, now);
    }
}

static void service(uint32_t now) {
    consolePoll();
    // A host state arriving mid-scan ends the scan so USB takes over now.
    if (gBle && !gUsbMode && gUsb.active(now)) gBle->cancelScan();
    pollInputs(now);
    gApp.tick(now);
    lv_timer_handler();
}

// -------------------------------------------------------------------- BLE
static bool sendToBoombox(const char* action, const String* value) {
    if (gUsbMode) return gUsb.sendCommand(action, value, millis());
    if (gLink != Link::Playing || !gBle || !gBle->isConnected()) return false;
    return gBle->sendCommand(String(action), value);
}

static void onPinEntered(const String& pin) {
    if (!gBle) return;
    Serial.printf("[pair] submitting PIN %s\n", pin.c_str());
    gPairPending = true;
    gPairDeadline = millis() + 9000;
    gPairDone = false;
    gBle->requestPair(pin,
        [](bool ok, const String& token, const String& bid,
           const String& bname, const String& error) {
            // NimBLE host task: no LVGL here, just hand the result over.
            portENTER_CRITICAL(&gPairMux);
            gPairOk = ok;
            gPairToken = token;
            gPairId = bid;
            gPairName = bname;
            gPairError = error;
            gPairDone = true;
            portEXIT_CRITICAL(&gPairMux);
        }, 8000);
}

static void handlePairResult(uint32_t now) {
    if (!gPairPending) return;
    if (gPairDone) {
        portENTER_CRITICAL(&gPairMux);
        const bool ok = gPairOk;
        const String token = gPairToken, bid = gPairId, bname = gPairName,
                     err = gPairError;
        gPairDone = false;
        portEXIT_CRITICAL(&gPairMux);
        gPairPending = false;
        if (!ok) {
            Serial.printf("[pair] failed: %s\n", err.c_str());
            gApp.pairFailed(err == "bad_pin" ? "Wrong PIN - try again"
                          : err == "no_active_pin" ? "No active PIN - start pairing on the boombox"
                          : "Pairing failed - try again");
            return;
        }
        PairedBoombox pb;
        pb.id = bid;
        pb.name = bname;
        pb.auth_token = token;
        pb.paired_at = (uint32_t)time(nullptr);
        PairedBoomboxStore::save(pb);
        gPair = pb;
        gHaveSaved = true;
        Serial.printf("[pair] paired with %s (%s)\n", bname.c_str(), bid.c_str());
        gApp.pairSucceeded();
        gLink = Link::Playing;
        return;
    }
    if ((int32_t)(now - gPairDeadline) > 0) {
        gPairPending = false;
        Serial.println("[pair] no response");
        gApp.pairFailed("No response - try again");
    }
}

static const char* searchingTitle() {
    return gHaveSaved ? "Reconnecting..." : "Looking for a boombox";
}

static void linkStep(uint32_t now) {
    if ((gLink == Link::Pair || gLink == Link::Playing) && gBle && !gBle->isConnected()) {
        Serial.println("[link] dropped - rescanning");
        gPlayingWired = false;
        gPairPending = false;
        gApp.showSearching(searchingTitle(), "Lost the boombox");
        gLink = Link::Scan;
    }

    switch (gLink) {
        case Link::Paused:
            break;
        case Link::Scan: {
            if ((int32_t)(now - gNextScanAt) < 0) break;
            gApp.setSearchingStatus("Scanning over Bluetooth...");
            gPendingAddress = gBle->findFirstBoomboxNonBlocking(8000);
            if (gLink != Link::Scan) break;   // console paused/changed us mid-scan
            if (gUsb.active(millis())) break; // USB took over mid-scan
            if (gPendingAddress.length() == 0) {
                gApp.setSearchingStatus("No boombox found - retrying");
                gNextScanAt = millis() + 1500;
                break;
            }
            gLink = Link::Connect;
            break;
        }
        case Link::Connect: {
            Serial.printf("[link] connecting to %s\n", gPendingAddress.c_str());
            gApp.setSearchingStatus("Connecting...");
            lv_timer_handler();
            if (!gBle->connect(gPendingAddress)) {
                gApp.setSearchingStatus("Connect failed - rescanning");
                gNextScanAt = millis() + 800;
                gLink = Link::Scan;
                break;
            }
            if (gUsb.active(millis())) {      // USB took over mid-connect
                gBle->disconnect();
                gLink = Link::Scan;
                break;
            }
            String bid, bname;
            const bool info = gBle->readDeviceInfo(bid, bname);
            if (gHaveSaved && info && bid.length() && bid == gPair.id) {
                Serial.printf("[link] resumed pairing with %s\n", bname.c_str());
                if (bname.length()) gPair.name = bname;
                gLink = Link::Playing;
                break;
            }
            Serial.println("[link] connected; not paired with this boombox");
            gApp.startPairing(info ? bname : String(), onPinEntered);
            gLink = Link::Pair;
            break;
        }
        case Link::Pair:
            handlePairResult(now);
            break;
        case Link::Playing:
            if (!gPlayingWired) {
                gPlayingWired = true;
                Serial.printf("[link] playing with %s\n", gPair.name.c_str());
                gBle->onState([](const BoomboxState& s) { gApp.onState(s, millis()); });
                gBle->onStatus([](bool) {});
                gApp.showFace();
                if (!gBle->subscribeState())
                    Serial.println("[link] state subscribe failed");
            }
            break;
    }
}

// -------------------------------------------------------------------- USB
static void enterUsbMode() {
    gUsbMode = true;
    if (gBle) {
        gBle->cancelScan();
        if (gBle->isConnected()) gBle->disconnect();
    }
    gPlayingWired = false;
    gPairPending = false;
    gLink = Link::Scan;      // where BLE resumes if USB goes quiet
    gNextScanAt = 0;
    Serial.println("[usb] host link active - BLE paused");
    gApp.showFace();
}

static void leaveUsbMode() {
    gUsbMode = false;
    if (gLink == Link::Paused) return;   // demo mode: stay put
    Serial.println("[usb] host link quiet - falling back to BLE");
    gLink = Link::Scan;
    gNextScanAt = 0;
    gApp.showSearching(searchingTitle(), "USB link lost");
}

// ---------------------------------------------------------------- console
static void registerCommands() {
    consoleOn("enc", "enc +N|-N  inject encoder detents", [](const String& a) {
        gApp.onDetents(a.toInt(), millis());
    });
    consoleOn("click", "inject a click", [](const String&) {
        gApp.onGesture(Gesture::Click, millis());
    });
    consoleOn("dclick", "inject a double click", [](const String&) {
        gApp.onGesture(Gesture::DoubleClick, millis());
    });
    consoleOn("long", "inject a long press", [](const String&) {
        gApp.onGesture(Gesture::LongPress, millis());
    });
    consoleOn("tap", "tap X Y  inject a touch tap", [](const String& a) {
        const int sp = a.indexOf(' ');
        injectTap(a.toInt(), sp > 0 ? a.substring(sp + 1).toInt() : 240);
    });
    consoleOn("state", "state {json}  inject a BoomboxState (enters demo mode)",
              [](const String& a) {
        // Accept {"ok":true,"data":{...}} or the bare data object.
        String body = a;
        if (body.indexOf("\"data\"") < 0) body = String("{\"ok\":true,\"data\":") + a + "}";
        BoomboxState s;
        if (!boombox::parseStateJson(body, s)) {
            Serial.println("[state] parse failed");
            return;
        }
        if (gLink != Link::Paused) {
            Serial.println("[state] demo mode: BLE + USB links paused (ble on to resume)");
            gLink = Link::Paused;
        }
        gApp.onState(s, millis());
        gApp.showFace();
        Serial.printf("[state] injected title='%s' vol=%d theme=%d\n",
                      s.track.title.c_str(), s.volume, s.theme.present());
    });
    consoleOn("demo", "demo face|pair|search  show a screen with BLE paused",
              [](const String& a) {
        gLink = Link::Paused;
        if (a == "pair") gApp.startPairing("Boombox", [](const String& pin) {
            Serial.printf("[demo] PIN entered: %s\n", pin.c_str());
            gApp.pairFailed("Demo - not sent");
        });
        else if (a == "search") gApp.showSearching(searchingTitle(), "Scanning over Bluetooth...");
        else gApp.showFace();
    });
    consoleOn("ble", "ble on|off  resume/pause the link state machine (BLE + USB)",
              [](const String& a) {
        if (a == "off") {
            gLink = Link::Paused;
        } else {
            if (gBle && gBle->isConnected()) gBle->disconnect();
            gUsbMode = false;      // re-evaluated next loop (USB still wins if live)
            gPlayingWired = false;
            gLink = Link::Scan;
            gNextScanAt = 0;
            gApp.showSearching(searchingTitle(), "");
        }
        Serial.printf("[ble] %s\n", gLink == Link::Paused ? "paused" : "scanning");
    });
    consoleOn("usb", "USB host link status", [](const String&) {
        Serial.printf("[usb] mode=%d active=%d states=%u cmds=%u bad=%u\n",
                      (int)gUsbMode, (int)gUsb.active(millis()),
                      (unsigned)gUsb.statesReceived(), (unsigned)gUsb.commandsSent(),
                      (unsigned)gUsb.badLines());
    });
    consoleOn("testscreen", "colour bars + ring (BLE paused)", [](const String&) {
        gLink = Link::Paused;
        gApp.showTest();
    });
    consoleOn("unpair", "forget the paired boombox", [](const String&) {
        PairedBoomboxStore::clear();
        gHaveSaved = false;
        Serial.println("[pair] cleared");
    });
    consoleOn("wake", "wake the backlight (no other action)", [](const String&) {
        gApp.wake(millis());
    });
    consoleOn("reboot", "restart", [](const String&) { ESP.restart(); });
    consoleOn("bl", "bl N  backlight 0-255", [](const String& a) {
        setBacklight((uint8_t)constrain(a.toInt(), 0, 255));
    });
    consoleOn("info", "board + link status", [](const String&) {
        const BoardStatus& s = boardStatus();
        Serial.printf("[info] expander=%d panel=%d touch=%d psram=%d heap=%u "
                      "psram_free=%u enc_raw=%ld link=%d connected=%d paired=%d "
                      "usb=%d power=%s boombox=%s\n",
                      s.expander, s.panel, s.touch, s.psram,
                      (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getFreePsram(),
                      (long)encoderRawCount(), (int)gLink,
                      gBle ? (int)gBle->isConnected() : 0, (int)gHaveSaved,
                      (int)gUsbMode, gApp.powerName(), gApp.boomboxPowerName());
    });
}

// ------------------------------------------------------------- setup/loop
void setup() {
    Serial.setRxBufferSize(4096);
    Serial.setTxBufferSize(4096);
    Serial.begin(115200);
    delay(300);
    Serial.println();
    Serial.println("=== boombox-remote firmware ===");
    Serial.printf("profile: %s\n", PROFILE_ID);
    Serial.printf("version: %s\n", BOOMBOX_FW_VERSION);

    boardBegin();
    lvglBegin();
    gApp.begin(sendToBoombox);
    setTouchGate([](int16_t x, int16_t y) { return gApp.onTouchDown(x, y, millis()); });

    gHaveSaved = PairedBoomboxStore::load(gPair);
    if (gHaveSaved)
        Serial.printf("[boot] saved pairing: %s (%s)\n", gPair.name.c_str(), gPair.id.c_str());
    else
        Serial.println("[boot] no saved pairing");
    gApp.showSearching(searchingTitle(), "Starting Bluetooth...");
    lv_timer_handler();

    consoleBegin();
    registerCommands();
    gUsb.begin([](const BoomboxState& s) {
        if (gLink == Link::Paused) return;   // demo mode owns the face
        gApp.onState(s, millis());
    });
    gUsb.announce();

    gBle = new BleClient();
    // Keep the console, the knob and LVGL alive during the 8 s scans.
    gBle->setIdleHook([]() { service(millis()); });
    Serial.println("ready.");
}

void loop() {
    const uint32_t now = millis();
    service(now);
    const bool usb = gLink != Link::Paused && gUsb.active(now);
    if (usb && !gUsbMode) enterUsbMode();
    else if (!usb && gUsbMode) leaveUsbMode();
    if (!gUsbMode) {
        if (gBle) gBle->pumpEvents();
        linkStep(now);
    }
    delay(5);
}
