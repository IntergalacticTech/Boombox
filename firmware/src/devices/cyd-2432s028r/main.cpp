// boombox-remote firmware — CYD 2.8" entry point.
//
// Phase 2 — Stage 2 stub: prints to serial so the first flash is verifiable
// without any display or network code in the way. Later tasks bring up the
// device shell (display + touch + LDR), the shared core library (WiFi,
// HTTP, WS, NVS, action dispatch), and the LVGL UI screens.

#include <Arduino.h>

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
    Serial.printf("psram:   %u bytes\n", ESP.getPsramSize());
    Serial.println("ready.");
}

void loop() {
    delay(2000);
    Serial.printf("alive [uptime %lu s]\n", millis() / 1000);
}
