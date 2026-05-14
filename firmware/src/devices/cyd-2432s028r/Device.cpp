// CYD 2.8" device shell — TFT_eSPI display + XPT2046 resistive touch +
// LDR backlight control. Implements IDevice; the shared core's app loop
// drives pollInputs() and brightness via this class.

#include "Device.h"
#include <SPI.h>
#include <TFT_eSPI.h>
#include <XPT2046_Touchscreen.h>
#include <lvgl.h>

namespace boombox {

// Hardware (CYD pins — verified against random-nerd-tutorials reference).
static constexpr int PIN_BACKLIGHT = 21;
static constexpr int PIN_LDR       = 34;
static constexpr int PIN_TOUCH_CS  = 33;
static constexpr int PIN_TOUCH_IRQ = 36;
static constexpr int TOUCH_SCK     = 25;
static constexpr int TOUCH_MISO    = 39;
static constexpr int TOUCH_MOSI    = 32;

static TFT_eSPI _tft;
static SPIClass _touchSpi(VSPI);
static XPT2046_Touchscreen _touch(PIN_TOUCH_CS, PIN_TOUCH_IRQ);

static lv_display_t* _disp = nullptr;
static lv_color_t _draw_buf[240 * 40];   // partial render buffer

static void _flush(lv_display_t* disp, const lv_area_t* area, uint8_t* px) {
    uint32_t w = area->x2 - area->x1 + 1;
    uint32_t h = area->y2 - area->y1 + 1;
    _tft.startWrite();
    _tft.setAddrWindow(area->x1, area->y1, w, h);
    // LVGL outputs RGB565 in native ESP32 little-endian; tell pushColors
    // to swap to the big-endian byte order ST7789 expects on the wire.
    _tft.pushColors(reinterpret_cast<uint16_t*>(px), w * h, true);
    _tft.endWrite();
    lv_display_flush_ready(disp);
}

static void _read_touch(lv_indev_t* /*indev*/, lv_indev_data_t* data) {
    if (_touch.tirqTouched() && _touch.touched()) {
        TS_Point p = _touch.getPoint();
        // Calibration for typical CYD 2.8" raw → 240x320 mapping. Different
        // batches may need different coefficients; tweak if touch is offset.
        int x = map(p.x, 200, 3700, 0, 239);
        int y = map(p.y, 240, 3800, 0, 319);
        data->point.x = constrain(x, 0, 239);
        data->point.y = constrain(y, 0, 319);
        data->state = LV_INDEV_STATE_PRESSED;
    } else {
        data->state = LV_INDEV_STATE_RELEASED;
    }
}

void CydDevice::init() {
    pinMode(PIN_BACKLIGHT, OUTPUT);
    analogWrite(PIN_BACKLIGHT, 200);   // ~78% initial

    _tft.init();
    _tft.setRotation(0);
    _tft.fillScreen(TFT_BLACK);

    _touchSpi.begin(TOUCH_SCK, TOUCH_MISO, TOUCH_MOSI, PIN_TOUCH_CS);
    _touch.begin(_touchSpi);
    _touch.setRotation(0);

    lv_init();
    // LVGL 9 needs a runtime tick source — without this, lv_tick_get()
    // returns 0 forever, so the refresh timer fires once and then never
    // again (LVGL 8's compile-time LV_TICK_CUSTOM_SYS_TIME_EXPR is gone).
    lv_tick_set_cb([]() -> uint32_t { return millis(); });

    _disp = lv_display_create(240, 320);
    lv_display_set_flush_cb(_disp, _flush);
    lv_display_set_buffers(_disp, _draw_buf, nullptr,
                            sizeof(_draw_buf), LV_DISPLAY_RENDER_MODE_PARTIAL);

    lv_indev_t* indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, _read_touch);
}

void CydDevice::pollInputs() {
    // LVGL drives input via _read_touch on its own schedule when
    // lv_timer_handler() runs in the main loop.
}

void CydDevice::setBrightness(uint8_t pct) {
    if (pct > 100) pct = 100;
    analogWrite(PIN_BACKLIGHT, map(pct, 0, 100, 0, 255));
}

uint16_t CydDevice::readLdr() {
    return analogRead(PIN_LDR);
}

DeviceCapabilities CydDevice::caps() const {
    return DeviceCapabilities{true, true, true, false};
}

void CydDevice::paintSolid(uint16_t color565) {
    _tft.fillScreen(color565);
}

} // namespace boombox
