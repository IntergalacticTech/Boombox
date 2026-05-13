// boombox-remote firmware — CYD 2.8" entry point.
//
// SINGLE-SCREEN architecture: instead of swapping LVGL screens (which has
// broken rendering on this stack post-BLE), one persistent screen hosts
// three modes via toggled visibility groups. The state machine in loop()
// drives transitions.
//
// BLE-first boot flow:
//   1. init device (display, touch, LDR, LVGL) + build the single UI
//   2. init BLE central, kick off async scan for boomboxes
//   3. on scan hit, connect, switch UI to PAIR mode (PIN keypad)
//   4. on PIN entered + accepted, switch UI to PLAYING mode
//   5. subscribe to state pushes; the UI listens for updates

#include <Arduino.h>
#include <lvgl.h>
#include "Device.h"
#include "storage/PairedBoombox.h"
#include "transport/BleClient.h"
#include "action/ActionDispatch.h"
#include "state/BoomboxState.h"
#include "ui/SingleScreen.h"

using boombox::PairedBoombox;
using boombox::PairedBoomboxStore;

static boombox::CydDevice gDevice;
static boombox::BleClient* gBle = nullptr;
static boombox::ActionDispatch* gActions = nullptr;
static boombox::ui::SingleScreen gUI_obj;

// State machine for boot — driven from loop() so all BLE blocking
// happens AFTER setup() so the UI keeps rendering.
enum class BootState {
    Scan,
    Connect,
    Pair,
    Playing,
};
static BootState gBootState = BootState::Scan;
static String gPendingAddress;
static PairedBoombox gPendingPair;

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println();
    Serial.println("=== boombox-remote firmware ===");
    Serial.printf("profile: %s\n", PROFILE_ID);
    Serial.printf("version: %s\n", BOOMBOX_FW_VERSION);

    // Lock CPU/APB to 240 MHz so BLE doesn't shift the clock during ops.
    setCpuFrequencyMhz(240);

    gDevice.init();
    gUI_obj.build();
    gUI_obj.showSearching("Looking for a boombox over Bluetooth…");
    Serial.println("[boot] device + UI ready");

    gBle = new boombox::BleClient();
    Serial.println("[boot] BLE central initialized");

    // Always re-pair on boot for Phase 2 MVP.
    PairedBoomboxStore::clear();
    Serial.println("ready.");
}

void loop() {
    lv_timer_handler();
    gUI_obj.tickPair(millis());

    // Boot state machine — runs ONE step per loop iteration so LVGL
    // gets to tick frequently in between.
    switch (gBootState) {
        case BootState::Scan: {
            Serial.println("[loop] starting BLE scan");
            gUI_obj.setSearchingStatus("Scanning over Bluetooth…");
            gPendingAddress = gBle->findFirstBoomboxNonBlocking(8000);
            if (gPendingAddress.length() == 0) {
                gUI_obj.setSearchingStatus("No boomboxes found — retrying…");
                delay(1000);
                break;   // stay in Scan, retry on next loop tick
            }
            gBootState = BootState::Connect;
            break;
        }
        case BootState::Connect: {
            Serial.printf("[loop] connecting to %s\n", gPendingAddress.c_str());
            gUI_obj.setSearchingStatus("Connecting…");
            if (!gBle->connect(gPendingAddress)) {
                gUI_obj.setSearchingStatus("Connect failed — rescanning");
                delay(800);
                gBootState = BootState::Scan;
                break;
            }
            Serial.println("[loop] connected; showing pair screen");
            gUI_obj.showPair(gBle, [](const PairedBoombox& pb) {
                gPendingPair = pb;
                gBootState = BootState::Playing;
            });
            gBootState = BootState::Pair;
            break;
        }
        case BootState::Pair: {
            // UI handles PIN entry + pair callback. Nothing to do here.
            break;
        }
        case BootState::Playing: {
            static bool wired = false;
            if (!wired) {
                wired = true;
                Serial.printf("[loop] entering Playing for %s\n",
                               gPendingPair.name.c_str());
                gActions = new boombox::ActionDispatch(gBle);
                gUI_obj.showPlaying(gActions, gPendingPair.name);
                gBle->onState([](const boombox::BoomboxState& s) {
                    gUI_obj.onStateUpdate(s);
                });
                gBle->onStatus([](bool ok) {
                    gUI_obj.onConnectionChange(ok);
                });
                gBle->subscribeState();
            }
            break;
        }
    }

    delay(20);
}
