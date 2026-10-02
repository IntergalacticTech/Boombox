// LVGL glue for the CrowPanel: display flush into Arduino_GFX's PSRAM
// framebuffer, a pointer indev for the CST8xx touch, and test hooks to inject
// taps over serial.
#pragma once
#include <lvgl.h>
#include <functional>

namespace knob {

// Creates the LVGL display + touch indev. Call after boardBegin().
void lvglBegin();

lv_display_t* lvglDisplay();
lv_indev_t*   lvglTouch();

// Called on every touch-down edge with the screen coordinate. Return false
// to swallow the whole touch (e.g. a tap that only wakes the backlight);
// LVGL then sees nothing until the finger lifts.
using TouchGate = std::function<bool(int16_t x, int16_t y)>;
void setTouchGate(TouchGate gate);

// Serial-injected tap: pressed at (x,y) for a few indev reads, then released.
void injectTap(int16_t x, int16_t y);

}  // namespace knob
