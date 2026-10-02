// boombox-remote firmware — CrowPanel 2.1" rotary knob (bring-up build).
//
// Phase 1: prove the hardware. Shows colour bars and a ring, logs encoder
// detents, switch press/release and touch to serial, and answers the debug
// console (snap / enc / click / dclick / long / tap).

#include <Arduino.h>
#include <lvgl.h>

#include "board/Board.h"
#include "board/LvglPort.h"
#include "DebugConsole.h"
#include "KnobGesture.h"

using namespace knob;

static GestureRecognizer gGesture;
static lv_obj_t* gTestRing = nullptr;
static lv_obj_t* gTestLabel = nullptr;
static int gTestValue = 50;

static void buildTestScreen() {
    lv_obj_t* scr = lv_screen_active();
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);

    // Eight vertical colour bars: white, yellow, cyan, green, magenta, red,
    // blue, black — the classic order, so a swapped R/B shows at a glance.
    static const uint32_t BARS[8] = {0xFFFFFF, 0xFFFF00, 0x00FFFF, 0x00FF00,
                                     0xFF00FF, 0xFF0000, 0x0000FF, 0x000000};
    for (int i = 0; i < 8; i++) {
        lv_obj_t* b = lv_obj_create(scr);
        lv_obj_remove_style_all(b);
        lv_obj_set_size(b, 60, 480);
        lv_obj_set_pos(b, i * 60, 0);
        lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(b, lv_color_hex(BARS[i]), 0);
    }

    gTestRing = lv_arc_create(scr);
    lv_obj_set_size(gTestRing, 440, 440);
    lv_obj_center(gTestRing);
    lv_arc_set_bg_angles(gTestRing, 135, 45);
    lv_arc_set_range(gTestRing, 0, 100);
    lv_arc_set_value(gTestRing, gTestValue);
    lv_obj_set_style_arc_width(gTestRing, 18, LV_PART_MAIN);
    lv_obj_set_style_arc_width(gTestRing, 18, LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(gTestRing, lv_color_hex(0x202020), LV_PART_MAIN);
    lv_obj_set_style_arc_color(gTestRing, lv_color_hex(0xFF8800), LV_PART_INDICATOR);
    lv_obj_remove_flag(gTestRing, LV_OBJ_FLAG_CLICKABLE);

    lv_obj_t* disc = lv_obj_create(scr);
    lv_obj_remove_style_all(disc);
    lv_obj_set_size(disc, 220, 220);
    lv_obj_center(disc);
    lv_obj_set_style_radius(disc, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(disc, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(disc, lv_color_hex(0x101018), 0);

    gTestLabel = lv_label_create(scr);
    lv_obj_set_style_text_color(gTestLabel, lv_color_white(), 0);
    lv_obj_set_style_text_font(gTestLabel, &lv_font_montserrat_28, 0);
    lv_obj_set_style_text_align(gTestLabel, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_text_fmt(gTestLabel, "BRING-UP\n%d", gTestValue);
    lv_obj_center(gTestLabel);
}

static void setTestValue(int v, const char* why) {
    gTestValue = constrain(v, 0, 100);
    lv_arc_set_value(gTestRing, gTestValue);
    lv_label_set_text_fmt(gTestLabel, "%s\n%d", why, gTestValue);
}

static void onDetents(int32_t d, const char* src) {
    Serial.printf("[enc] %s detents=%+ld raw=%ld\n", src, (long)d,
                  (long)encoderRawCount());
    setTestValue(gTestValue + d * 2, "TURN");
}

static void onGesture(Gesture g, const char* src) {
    if (g == Gesture::None) return;
    Serial.printf("[btn] %s gesture=%s\n", src, gestureName(g));
    setTestValue(gTestValue, g == Gesture::Click ? "CLICK"
                           : g == Gesture::DoubleClick ? "DOUBLE" : "LONG");
}

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
    buildTestScreen();

    consoleBegin();
    consoleOn("enc", "enc +N|-N  inject encoder detents", [](const String& a) {
        onDetents(a.toInt(), "inject");
    });
    consoleOn("click", "inject a click", [](const String&) {
        onGesture(Gesture::Click, "inject");
    });
    consoleOn("dclick", "inject a double click", [](const String&) {
        onGesture(Gesture::DoubleClick, "inject");
    });
    consoleOn("long", "inject a long press", [](const String&) {
        onGesture(Gesture::LongPress, "inject");
    });
    consoleOn("tap", "tap X Y  inject a touch tap", [](const String& a) {
        int sp = a.indexOf(' ');
        injectTap(a.toInt(), sp > 0 ? a.substring(sp + 1).toInt() : 240);
    });
    consoleOn("bl", "bl N  backlight 0-255", [](const String& a) {
        setBacklight((uint8_t)constrain(a.toInt(), 0, 255));
    });
    consoleOn("info", "board status", [](const String&) {
        const BoardStatus& s = boardStatus();
        Serial.printf("[info] expander=%d panel=%d touch=%d psram=%d "
                      "heap=%u psram_free=%u enc_raw=%ld\n",
                      s.expander, s.panel, s.touch, s.psram,
                      (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getFreePsram(),
                      (long)encoderRawCount());
    });
    Serial.println("ready.");
}

void loop() {
    const uint32_t now = millis();
    consolePoll();

    const int32_t d = encoderTakeDetents();
    if (d) onDetents(d, "knob");

    bool down;
    if (buttonPoll(now, down)) {
        Serial.printf("[btn] %s\n", down ? "press" : "release");
        onGesture(down ? gGesture.press(now) : gGesture.release(now), "knob");
    }
    onGesture(gGesture.tick(now), "knob");

    lv_timer_handler();
    delay(5);
}
