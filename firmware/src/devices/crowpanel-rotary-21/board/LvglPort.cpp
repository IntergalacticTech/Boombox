#include "LvglPort.h"
#include "Board.h"

#include <Arduino.h>
#include <Arduino_GFX_Library.h>
#include <esp_heap_caps.h>

namespace knob {

namespace {
lv_display_t* g_disp = nullptr;
lv_indev_t* g_touch = nullptr;
TouchGate g_gate;

// Partial render buffers in internal SRAM (fast to draw into); the flush
// copies the dirty rectangle into the panel's PSRAM framebuffer.
constexpr int BUF_LINES = 40;

// Injected tap: number of indev reads left to report "pressed".
volatile int g_inject_reads = 0;
int16_t g_inject_x = 0, g_inject_y = 0;

void flushCb(lv_display_t* disp, const lv_area_t* area, uint8_t* px) {
    Arduino_RGB_Display* gfx = boardGfx();
    if (gfx) {
        const int32_t w = area->x2 - area->x1 + 1;
        const int32_t h = area->y2 - area->y1 + 1;
        gfx->draw16bitRGBBitmap(area->x1, area->y1,
                                reinterpret_cast<uint16_t*>(px), w, h);
    }
    lv_display_flush_ready(disp);
}

void touchCb(lv_indev_t*, lv_indev_data_t* data) {
    static bool was_down = false;
    static bool swallowing = false;
    static int16_t last_x = 0, last_y = 0;

    int16_t x = 0, y = 0;
    bool down = false;
    if (g_inject_reads > 0) {
        g_inject_reads--;
        down = true;
        x = g_inject_x;
        y = g_inject_y;
    } else {
        down = touchRead(x, y);
    }

    if (down && !was_down) {
        Serial.printf("[touch] down x=%d y=%d\n", x, y);
        swallowing = g_gate ? !g_gate(x, y) : false;
    } else if (!down && was_down) {
        Serial.printf("[touch] up x=%d y=%d%s\n", last_x, last_y,
                      swallowing ? " (swallowed)" : "");
    }
    was_down = down;

    if (down) {
        // CST8xx jitters by a few px while a finger rests; hold the last
        // point for tiny moves so LVGL doesn't re-render on noise.
        if (abs(x - last_x) >= 4 || abs(y - last_y) >= 4) {
            last_x = x;
            last_y = y;
        }
    }
    data->point.x = last_x;
    data->point.y = last_y;
    data->state = (down && !swallowing) ? LV_INDEV_STATE_PRESSED
                                        : LV_INDEV_STATE_RELEASED;
    if (!down) swallowing = false;
}
}  // namespace

void lvglBegin() {
    lv_init();
    lv_tick_set_cb([]() -> uint32_t { return millis(); });

    const size_t bytes = SCREEN_W * BUF_LINES * sizeof(uint16_t);
    void* b1 = heap_caps_malloc(bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    void* b2 = heap_caps_malloc(bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!b1 || !b2) {
        // Fall back to PSRAM — slower, but it still renders.
        Serial.println("[lvgl] internal draw buffers unavailable, using PSRAM");
        if (!b1) b1 = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM);
        if (!b2) b2 = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM);
    }

    g_disp = lv_display_create(SCREEN_W, SCREEN_H);
    lv_display_set_color_format(g_disp, LV_COLOR_FORMAT_RGB565);
    lv_display_set_flush_cb(g_disp, flushCb);
    lv_display_set_buffers(g_disp, b1, b2, bytes, LV_DISPLAY_RENDER_MODE_PARTIAL);

    g_touch = lv_indev_create();
    lv_indev_set_type(g_touch, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(g_touch, touchCb);
    lv_indev_set_display(g_touch, g_disp);
}

lv_display_t* lvglDisplay() { return g_disp; }
lv_indev_t* lvglTouch() { return g_touch; }

void setTouchGate(TouchGate gate) { g_gate = std::move(gate); }

void injectTap(int16_t x, int16_t y) {
    g_inject_x = x;
    g_inject_y = y;
    g_inject_reads = 3;
}

}  // namespace knob
