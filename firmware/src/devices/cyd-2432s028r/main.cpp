// boombox-remote firmware — CYD 2.8" entry point.
//
// Phase 2 — Stage 4 milestone: brings up the display + touch and paints a
// centered green square via LVGL. Confirms the device shell works before
// the Stage 5 UI screens stack on top.

#include <Arduino.h>
#include <lvgl.h>
#include "Device.h"

static boombox::CydDevice gDevice;

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println();
    Serial.println("=== boombox-remote firmware ===");
    Serial.printf("profile: %s\n", PROFILE_ID);
    Serial.printf("version: %s\n", BOOMBOX_FW_VERSION);

    gDevice.init();

    // Smoke object so we know LVGL is flushing pixels onto the panel.
    lv_obj_t* sq = lv_obj_create(lv_screen_active());
    lv_obj_set_size(sq, 120, 120);
    lv_obj_center(sq);
    lv_obj_set_style_bg_color(sq, lv_color_make(64, 200, 96), 0);
    lv_obj_set_style_border_width(sq, 0, 0);
    lv_obj_set_style_radius(sq, 12, 0);

    lv_obj_t* lbl = lv_label_create(sq);
    lv_label_set_text(lbl, "boombox-remote");
    lv_obj_set_style_text_color(lbl, lv_color_make(0, 0, 0), 0);
    lv_obj_center(lbl);

    Serial.println("ready.");
}

void loop() {
    lv_timer_handler();
    delay(5);
}
