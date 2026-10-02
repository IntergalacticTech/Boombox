// Host unit tests for lib/knob-logic: `pio test -e native`.
#include <unity.h>

#include "CssColor.h"
#include "KnobGesture.h"
#include "VolumeCoalescer.h"

using namespace knob;

void setUp() {}
void tearDown() {}

// ------------------------------------------------------------ CSS colours
static void assertRgba(const char* s, int r, int g, int b, int a) {
    Rgba c;
    TEST_ASSERT_TRUE_MESSAGE(parseCssColor(s, c), s);
    TEST_ASSERT_EQUAL_INT_MESSAGE(r, c.r, s);
    TEST_ASSERT_EQUAL_INT_MESSAGE(g, c.g, s);
    TEST_ASSERT_EQUAL_INT_MESSAGE(b, c.b, s);
    TEST_ASSERT_EQUAL_INT_MESSAGE(a, c.a, s);
}

void test_hex_forms() {
    assertRgba("#B9C3A5", 0xB9, 0xC3, 0xA5, 255);
    assertRgba("#07060c", 0x07, 0x06, 0x0c, 255);
    assertRgba("#fff", 255, 255, 255, 255);
    assertRgba("#0f08", 0, 255, 0, 136);
    assertRgba("#11223380", 0x11, 0x22, 0x33, 0x80);
    assertRgba("  #abcdef  ", 0xab, 0xcd, 0xef, 255);
}

void test_rgb_rgba_forms() {
    assertRgba("rgba(255,255,255,0.08)", 255, 255, 255, 20);
    assertRgba("rgba(0, 0, 0, .5)", 0, 0, 0, 128);
    assertRgba("rgb(12, 34, 56)", 12, 34, 56, 255);
    assertRgba("RGB(300, -4, 10)", 255, 0, 10, 255);
    assertRgba("rgb(100% 0% 50% / 25%)", 255, 0, 128, 64);
    assertRgba("rgba(10,20,30)", 10, 20, 30, 255);
}

void test_keywords_and_garbage() {
    assertRgba("white", 255, 255, 255, 255);
    assertRgba("Transparent", 0, 0, 0, 0);
    Rgba c;
    c.r = 7;
    TEST_ASSERT_FALSE(parseCssColor("", c));
    TEST_ASSERT_FALSE(parseCssColor(nullptr, c));
    TEST_ASSERT_FALSE(parseCssColor("#12", c));
    TEST_ASSERT_FALSE(parseCssColor("#zzzzzz", c));
    TEST_ASSERT_FALSE(parseCssColor("rgb(1,2)", c));
    TEST_ASSERT_FALSE(parseCssColor("hsl(10, 50%, 50%)", c));
    TEST_ASSERT_FALSE(parseCssColor("'Inter', sans-serif", c));
    TEST_ASSERT_EQUAL_INT(7, c.r);   // untouched on failure
}

void test_blend_and_luma() {
    Rgba fg, bg;
    parseCssColor("rgba(255,255,255,0.5)", fg);
    parseCssColor("#000000", bg);
    Rgba o = blendOver(fg, bg);
    TEST_ASSERT_INT_WITHIN(1, 128, o.r);
    TEST_ASSERT_EQUAL_INT(255, o.a);
    Rgba white{255, 255, 255, 255}, black{0, 0, 0, 255};
    TEST_ASSERT_TRUE(luma(white) > 250);
    TEST_ASSERT_EQUAL_INT(0, luma(black));
    TEST_ASSERT_EQUAL_HEX32(0xFFFFFF, toHex(white));
    Rgba m = mix(black, white, 255);
    TEST_ASSERT_EQUAL_INT(255, m.g);
}

// --------------------------------------------------------------- gestures
void test_single_click_waits_for_double_window() {
    GestureRecognizer g(350, 600);
    TEST_ASSERT_EQUAL(Gesture::None, g.press(1000));
    TEST_ASSERT_EQUAL(Gesture::None, g.release(1100));
    TEST_ASSERT_EQUAL(Gesture::None, g.tick(1300));
    TEST_ASSERT_EQUAL(Gesture::None, g.tick(1450));
    TEST_ASSERT_EQUAL(Gesture::Click, g.tick(1451));
    TEST_ASSERT_EQUAL(Gesture::None, g.tick(2000));
}

void test_double_click() {
    GestureRecognizer g(350, 600);
    g.press(0);
    g.release(80);
    TEST_ASSERT_EQUAL(Gesture::None, g.tick(200));
    TEST_ASSERT_EQUAL(Gesture::None, g.press(300));
    TEST_ASSERT_EQUAL(Gesture::DoubleClick, g.release(380));
    TEST_ASSERT_EQUAL(Gesture::None, g.tick(1000));
}

void test_slow_second_press_is_two_clicks() {
    GestureRecognizer g(350, 600);
    g.press(0);
    g.release(80);
    TEST_ASSERT_EQUAL(Gesture::Click, g.tick(500));
    g.press(600);
    TEST_ASSERT_EQUAL(Gesture::None, g.release(650));
    TEST_ASSERT_EQUAL(Gesture::Click, g.tick(1100));
}

void test_late_tick_still_owes_click() {
    GestureRecognizer g(350, 600);
    g.press(0);
    g.release(50);
    // No tick in between; the next press arrives after the window.
    TEST_ASSERT_EQUAL(Gesture::Click, g.press(1000));
}

void test_long_press_fires_while_held_and_swallows_release() {
    GestureRecognizer g(350, 600);
    g.press(0);
    TEST_ASSERT_EQUAL(Gesture::None, g.tick(599));
    TEST_ASSERT_EQUAL(Gesture::LongPress, g.tick(600));
    TEST_ASSERT_EQUAL(Gesture::None, g.tick(900));
    TEST_ASSERT_EQUAL(Gesture::None, g.release(1200));
    TEST_ASSERT_EQUAL(Gesture::None, g.tick(2000));
}

void test_long_press_detected_on_release_without_tick() {
    GestureRecognizer g(350, 600);
    g.press(0);
    TEST_ASSERT_EQUAL(Gesture::LongPress, g.release(700));
}

void test_second_press_held_long_is_long_press() {
    GestureRecognizer g(350, 600);
    g.press(0);
    g.release(50);
    g.press(200);
    TEST_ASSERT_EQUAL(Gesture::LongPress, g.tick(800));
    TEST_ASSERT_EQUAL(Gesture::None, g.release(900));
    TEST_ASSERT_EQUAL(Gesture::None, g.tick(1500));
}

void test_double_disabled_clicks_immediately() {
    GestureRecognizer g(350, 600);
    g.setDoubleClickEnabled(false);
    g.press(0);
    TEST_ASSERT_EQUAL(Gesture::Click, g.release(60));
    g.press(100);
    TEST_ASSERT_EQUAL(Gesture::Click, g.release(160));
}

void test_reset_drops_gesture() {
    GestureRecognizer g(350, 600);
    g.press(0);
    g.reset();
    TEST_ASSERT_EQUAL(Gesture::None, g.release(50));
    TEST_ASSERT_EQUAL(Gesture::None, g.tick(1000));
}

// ------------------------------------------------------- volume coalescer
void test_volume_optimistic_and_rate_limited() {
    VolumeCoalescer v(125, 1000);
    v.reported(40, 0);
    TEST_ASSERT_EQUAL_INT(40, v.displayed(0));
    TEST_ASSERT_EQUAL_INT(42, v.turn(1, 2, 10));
    TEST_ASSERT_EQUAL_INT(42, v.displayed(10));
    TEST_ASSERT_EQUAL_INT(42, v.pollSend(10));    // first send immediate
    v.turn(1, 2, 20);
    v.turn(1, 2, 30);
    TEST_ASSERT_EQUAL_INT(-1, v.pollSend(40));    // rate limited
    TEST_ASSERT_EQUAL_INT(46, v.displayed(40));
    TEST_ASSERT_EQUAL_INT(46, v.pollSend(135));   // final value goes out
    TEST_ASSERT_EQUAL_INT(-1, v.pollSend(500));
}

void test_volume_ignores_stale_reports_while_turning_then_settles() {
    VolumeCoalescer v(125, 1000);
    v.reported(40, 0);
    v.turn(5, 2, 100);                            // → 50
    v.reported(44, 300);                          // in-flight echo
    TEST_ASSERT_EQUAL_INT(50, v.displayed(300));
    TEST_ASSERT_EQUAL_INT(50, v.pollSend(300));
    v.reported(48, 900);                          // boombox clamped/lost one
    TEST_ASSERT_EQUAL_INT(50, v.displayed(1050));
    TEST_ASSERT_EQUAL_INT(48, v.displayed(1101)); // settled to the truth
    TEST_ASSERT_EQUAL_INT(50, v.turn(1, 2, 1200)); // next turn starts from 48
}

void test_volume_clamps() {
    VolumeCoalescer v;
    v.reported(98, 0);
    TEST_ASSERT_EQUAL_INT(100, v.turn(5, 2, 10));
    TEST_ASSERT_EQUAL_INT(0, v.turn(-80, 2, 20));
}

void test_volume_unknown_report() {
    VolumeCoalescer v;
    v.reported(-1, 0);
    TEST_ASSERT_EQUAL_INT(0, v.displayed(0));
    TEST_ASSERT_EQUAL_INT(4, v.turn(2, 2, 10));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_hex_forms);
    RUN_TEST(test_rgb_rgba_forms);
    RUN_TEST(test_keywords_and_garbage);
    RUN_TEST(test_blend_and_luma);
    RUN_TEST(test_single_click_waits_for_double_window);
    RUN_TEST(test_double_click);
    RUN_TEST(test_slow_second_press_is_two_clicks);
    RUN_TEST(test_late_tick_still_owes_click);
    RUN_TEST(test_long_press_fires_while_held_and_swallows_release);
    RUN_TEST(test_long_press_detected_on_release_without_tick);
    RUN_TEST(test_second_press_held_long_is_long_press);
    RUN_TEST(test_double_disabled_clicks_immediately);
    RUN_TEST(test_reset_drops_gesture);
    RUN_TEST(test_volume_optimistic_and_rate_limited);
    RUN_TEST(test_volume_ignores_stale_reports_while_turning_then_settles);
    RUN_TEST(test_volume_clamps);
    RUN_TEST(test_volume_unknown_report);
    return UNITY_END();
}
