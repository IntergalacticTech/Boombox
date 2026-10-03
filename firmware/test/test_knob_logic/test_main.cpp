// Host unit tests for lib/knob-logic: `pio test -e native`.
#include <unity.h>

#include "CssColor.h"
#include "HostLink.h"
#include "KnobGesture.h"
#include "ScreenPolicy.h"
#include "TextFold.h"
#include "VolumeCoalescer.h"
#include "VolumeAccel.h"

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

// -------------------------------------------------------------- text fold
void test_fold_to_ascii() {
    TEST_ASSERT_EQUAL_STRING("Plain ASCII 123", foldToAscii("Plain ASCII 123").c_str());
    TEST_ASSERT_EQUAL_STRING("Beyonce", foldToAscii("Beyonc\xC3\xA9").c_str());
    TEST_ASSERT_EQUAL_STRING("Motorhead - Ace's", foldToAscii("Mot\xC3\xB6rhead \xE2\x80\x94 Ace\xE2\x80\x99s").c_str());
    TEST_ASSERT_EQUAL_STRING("Strasse...", foldToAscii("Stra\xC3\x9F" "e\xE2\x80\xA6").c_str());
    TEST_ASSERT_EQUAL_STRING("?", foldToAscii("\xE6\x97\xA5").c_str());   // CJK
    TEST_ASSERT_EQUAL_STRING("a?", foldToAscii("a\xC3").c_str());           // truncated
    TEST_ASSERT_EQUAL_STRING("", foldToAscii(nullptr).c_str());
}

void test_volume_step_accelerates_with_speed() {
    TEST_ASSERT_EQUAL_INT(4,  volumeStepForGap(UINT32_MAX));  // first detent
    TEST_ASSERT_EQUAL_INT(4,  volumeStepForGap(300));         // slow click
    TEST_ASSERT_EQUAL_INT(6,  volumeStepForGap(80));          // brisk turn
    TEST_ASSERT_EQUAL_INT(10, volumeStepForGap(20));          // fast spin
}

// --------------------------------------------------------------- host link
static int feedAll(LineAssembler& la, const char* s, const char** last) {
    int lines = 0;
    for (; *s; s++) {
        if (la.feed(*s)) {
            lines++;
            if (last) *last = la.line();
        }
    }
    return lines;
}

void test_line_assembler_splits_lines() {
    LineAssembler la;
    const char* last = nullptr;
    TEST_ASSERT_EQUAL_INT(2, feedAll(la, "info\r\n\n{\"t\":\"hello\"}\n", &last));
    TEST_ASSERT_EQUAL_STRING("{\"t\":\"hello\"}", last);
    TEST_ASSERT_EQUAL_INT(0, feedAll(la, "partial", nullptr));
    TEST_ASSERT_EQUAL_INT(1, feedAll(la, " line\n", &last));
    TEST_ASSERT_EQUAL_STRING("partial line", last);
}

void test_line_assembler_drops_overlong_lines_whole() {
    LineAssembler la;
    for (size_t i = 0; i < LineAssembler::CAP + 10; i++)
        TEST_ASSERT_FALSE(la.feed('x'));
    TEST_ASSERT_FALSE(la.feed('\n'));          // the overlong line is gone
    TEST_ASSERT_EQUAL_UINT32(1, la.dropped());
    const char* last = nullptr;
    TEST_ASSERT_EQUAL_INT(1, feedAll(la, "ok\n", &last));   // next line is clean
    TEST_ASSERT_EQUAL_STRING("ok", last);
    // Exactly CAP bytes still fits.
    for (size_t i = 0; i < LineAssembler::CAP; i++) la.feed('y');
    TEST_ASSERT_TRUE(la.feed('\n'));
    TEST_ASSERT_EQUAL_UINT32(LineAssembler::CAP, la.length());
}

void test_protocol_line_detection() {
    TEST_ASSERT_TRUE(isProtocolLine("{\"t\":\"state\"}"));
    TEST_ASSERT_TRUE(isProtocolLine("  {}"));
    TEST_ASSERT_FALSE(isProtocolLine("state {\"ok\":true}"));
    TEST_ASSERT_FALSE(isProtocolLine("[usb] host link active"));
    TEST_ASSERT_FALSE(isProtocolLine(""));
    TEST_ASSERT_FALSE(isProtocolLine(nullptr));
}

void test_link_window() {
    LinkWindow w(12000);
    TEST_ASSERT_FALSE(w.active(0));
    w.note(1000);
    TEST_ASSERT_TRUE(w.active(1000));
    TEST_ASSERT_TRUE(w.active(12999));
    TEST_ASSERT_FALSE(w.active(13000));
    // millis() wrap
    w.note(UINT32_MAX - 100);
    TEST_ASSERT_TRUE(w.active(5000));
    TEST_ASSERT_FALSE(w.active(12000));
    w.note(50);
    w.reset();
    TEST_ASSERT_FALSE(w.active(60));
}

void test_json_number() {
    TEST_ASSERT_TRUE(isJsonNumber("0.42"));
    TEST_ASSERT_TRUE(isJsonNumber("-3"));
    TEST_ASSERT_TRUE(isJsonNumber("0"));
    TEST_ASSERT_TRUE(isJsonNumber("1e2"));
    TEST_ASSERT_TRUE(isJsonNumber("2.5E-3"));
    TEST_ASSERT_FALSE(isJsonNumber(""));
    TEST_ASSERT_FALSE(isJsonNumber("mopidy"));
    TEST_ASSERT_FALSE(isJsonNumber("01"));
    TEST_ASSERT_FALSE(isJsonNumber("1."));
    TEST_ASSERT_FALSE(isJsonNumber(".5"));
    TEST_ASSERT_FALSE(isJsonNumber("nan"));
    TEST_ASSERT_FALSE(isJsonNumber(nullptr));
}

// ---------------------------------------------------------- screen policy
static const uint32_t DIM = SCREEN_DIM_AFTER_MS, OFF = SCREEN_OFF_AFTER_MS;

void test_screen_no_state_uses_input_timers() {
    TEST_ASSERT_EQUAL(Screen::Awake, screenPolicy(false, false, false, 0));
    TEST_ASSERT_EQUAL(Screen::Awake, screenPolicy(false, false, false, DIM));
    TEST_ASSERT_EQUAL(Screen::Dim, screenPolicy(false, false, false, DIM + 1));
    TEST_ASSERT_EQUAL(Screen::Dim, screenPolicy(false, false, false, OFF));
    TEST_ASSERT_EQUAL(Screen::Off, screenPolicy(false, false, false, OFF + 1));
    // Stale playing/asleep flags are ignored without a live state.
    TEST_ASSERT_EQUAL(Screen::Off, screenPolicy(false, true, false, OFF + 1));
    TEST_ASSERT_EQUAL(Screen::Awake, screenPolicy(false, false, true, 0));
}

void test_screen_stays_awake_while_playing() {
    TEST_ASSERT_EQUAL(Screen::Awake, screenPolicy(true, true, false, 0));
    TEST_ASSERT_EQUAL(Screen::Awake, screenPolicy(true, true, false, DIM + 1));
    TEST_ASSERT_EQUAL(Screen::Awake, screenPolicy(true, true, false, OFF + 1));
    TEST_ASSERT_EQUAL(Screen::Awake, screenPolicy(true, true, false, UINT32_MAX));
}

void test_screen_idle_boombox_dims_but_never_goes_off() {
    TEST_ASSERT_EQUAL(Screen::Awake, screenPolicy(true, false, false, 0));
    TEST_ASSERT_EQUAL(Screen::Awake, screenPolicy(true, false, false, DIM));
    TEST_ASSERT_EQUAL(Screen::Dim, screenPolicy(true, false, false, DIM + 1));
    TEST_ASSERT_EQUAL(Screen::Dim, screenPolicy(true, false, false, OFF + 1));
    TEST_ASSERT_EQUAL(Screen::Dim, screenPolicy(true, false, false, UINT32_MAX));
}

void test_screen_off_while_boombox_asleep() {
    // Asleep wins over a stale playing flag.
    TEST_ASSERT_EQUAL(Screen::Off, screenPolicy(true, false, true, DIM + 1));
    TEST_ASSERT_EQUAL(Screen::Off, screenPolicy(true, true, true, DIM + 1));
    // A knob input lights it for the dim window, then it goes straight off.
    TEST_ASSERT_EQUAL(Screen::Awake, screenPolicy(true, false, true, 0));
    TEST_ASSERT_EQUAL(Screen::Awake, screenPolicy(true, false, true, DIM));
    TEST_ASSERT_EQUAL(Screen::Off, screenPolicy(true, false, true, DIM + 1));
}

void test_screen_names() {
    TEST_ASSERT_EQUAL_STRING("awake", screenName(Screen::Awake));
    TEST_ASSERT_EQUAL_STRING("dim", screenName(Screen::Dim));
    TEST_ASSERT_EQUAL_STRING("off", screenName(Screen::Off));
}

void test_link_window_note_after_now_is_active() {
    LinkWindow w(12000);
    w.note(1005);                                   // state stamped at 1005…
    TEST_ASSERT_TRUE(w.active(1000));               // …checked with now=1000
    TEST_ASSERT_TRUE(w.active(1005 + 11999));
    TEST_ASSERT_FALSE(w.active(1005 + 12000));
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
    RUN_TEST(test_fold_to_ascii);
    RUN_TEST(test_volume_step_accelerates_with_speed);
    RUN_TEST(test_line_assembler_splits_lines);
    RUN_TEST(test_line_assembler_drops_overlong_lines_whole);
    RUN_TEST(test_protocol_line_detection);
    RUN_TEST(test_link_window);
    RUN_TEST(test_json_number);
    RUN_TEST(test_screen_no_state_uses_input_timers);
    RUN_TEST(test_screen_stays_awake_while_playing);
    RUN_TEST(test_screen_idle_boombox_dims_but_never_goes_off);
    RUN_TEST(test_screen_off_while_boombox_asleep);
    RUN_TEST(test_screen_names);
    RUN_TEST(test_link_window_note_after_now_is_active);
    return UNITY_END();
}
