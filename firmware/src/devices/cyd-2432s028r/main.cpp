// boombox-remote firmware — CYD 2.8" entry point.
//
// Phase 2 — Stage 3 stub: instantiates the shared core types so the
// linker pulls them in and we know they compile. Display + UI come in
// Stages 4-5; the actual app loop is wired in Task 15.

#include <Arduino.h>
#include "device/IDevice.h"
#include "device/IUI.h"
#include "state/BoomboxState.h"
#include "storage/PairedBoombox.h"
#include "storage/WifiCreds.h"
#include "transport/WifiManager.h"
#include "transport/HttpClient.h"
#include "transport/WsClient.h"
#include "action/ActionDispatch.h"

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println();
    Serial.println("=== boombox-remote firmware ===");
    Serial.printf("profile: %s\n", PROFILE_ID);
    Serial.printf("version: %s\n", BOOMBOX_FW_VERSION);
    Serial.printf("chip:    %s rev %d\n",
                   ESP.getChipModel(), ESP.getChipRevision());
    Serial.printf("flash:   %u bytes\n", ESP.getFlashChipSize());

    // Touch every shared type so the linker has to resolve them.
    boombox::BoomboxState st;
    boombox::WifiManager wifi;
    Serial.printf("wifi.tryStored placeholder = %d\n", (int)wifi.isConnected());
    Serial.printf("paired? %d\n", (int)boombox::PairedBoomboxStore::isPaired());
    Serial.println("ready.");
}

void loop() {
    delay(2000);
    Serial.printf("alive [uptime %lu s]\n", millis() / 1000);
}
