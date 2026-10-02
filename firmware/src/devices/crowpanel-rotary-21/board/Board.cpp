#include "Board.h"

#include <Wire.h>
#include <Arduino_GFX_Library.h>
#include <Adafruit_CST8XX.h>
#include <soc/gpio_reg.h>

namespace knob {

static BoardStatus g_status;

// ---------------------------------------------------------------- expander
//
// Minimal PCF8574 driver with a shadow byte. The chip is quasi-bidirectional:
// a pin reads back only while it's written high, so input pins are forced
// high on every write.
namespace {
uint8_t g_pcf_shadow = 0xFF;
constexpr uint8_t PCF_INPUT_MASK =
    (1u << pins::PCF_ENC_SW) | (1u << pins::PCF_TOUCH_INT);

bool pcfFlush() {
    Wire.beginTransmission(pins::PCF8574_ADDR);
    Wire.write(g_pcf_shadow | PCF_INPUT_MASK);
    return Wire.endTransmission() == 0;
}

bool pcfWrite(uint8_t pin, bool high) {
    if (high) g_pcf_shadow |= (1u << pin);
    else      g_pcf_shadow &= ~(1u << pin);
    return pcfFlush();
}

int pcfReadPort() {
    if (Wire.requestFrom((uint8_t)pins::PCF8574_ADDR, (uint8_t)1) != 1) return -1;
    return Wire.read();
}
}  // namespace

// ------------------------------------------------------------------ panel
namespace {
Arduino_DataBus* g_init_bus = nullptr;
Arduino_ESP32RGBPanel* g_rgb = nullptr;
Arduino_RGB_Display* g_gfx = nullptr;
uint8_t g_backlight = 0;
bool g_bl_attached = false;

void panelPowerCycle() {
    // The PCF8574 keeps its outputs through an ESP32 warm reset, so drop the
    // panel rail first: every boot then cold-starts the ST7701 the same way
    // a fresh plug-in does. Then Elecrow's sequence: power up, reset pulse.
    pcfWrite(pins::PCF_LCD_RESET, false);
    pcfWrite(pins::PCF_LCD_POWER, false);
    delay(120);
    pcfWrite(pins::PCF_LCD_POWER, true);
    delay(100);
    pcfWrite(pins::PCF_LCD_RESET, true);
    delay(100);
    pcfWrite(pins::PCF_LCD_RESET, false);
    delay(120);
    pcfWrite(pins::PCF_LCD_RESET, true);
    delay(120);
}

bool panelBegin() {
    g_init_bus = new Arduino_SWSPI(GFX_NOT_DEFINED /* DC: 9-bit SPI */,
                                   pins::LCD_CS, pins::LCD_SCK, pins::LCD_SDA,
                                   GFX_NOT_DEFINED /* MISO */);
    // Timings verbatim from Elecrow's RotaryScreen_2_1.ino.
    //
    // Colour order: Elecrow's sketch swaps the R and B fields of every pixel
    // in software before blitting (and sets MADCTL BGR below). Feeding LVGL's
    // R field to the B pins and vice versa is the same swap done by the pin
    // mux for free — both are 5-bit, so it's lossless.
    g_rgb = new Arduino_ESP32RGBPanel(
        pins::LCD_DE, pins::LCD_VSYNC, pins::LCD_HSYNC, pins::LCD_PCLK,
        pins::LCD_B0, pins::LCD_B1, pins::LCD_B2, pins::LCD_B3, pins::LCD_B4,
        pins::LCD_G0, pins::LCD_G1, pins::LCD_G2, pins::LCD_G3, pins::LCD_G4, pins::LCD_G5,
        pins::LCD_R0, pins::LCD_R1, pins::LCD_R2, pins::LCD_R3, pins::LCD_R4,
        1 /* hsync polarity */, 10 /* front porch */, 4 /* pulse */, 20 /* back porch */,
        1 /* vsync polarity */, 10 /* front porch */, 4 /* pulse */, 20 /* back porch */,
        0 /* pclk active neg */, 12000000 /* pclk Hz */, false /* big endian */,
        0 /* de idle high */, 0 /* pclk idle high */,
        480 * 20 /* bounce buffer px: two DMA bounce buffers, 20 lines each */);
    g_gfx = new Arduino_RGB_Display(
        SCREEN_W, SCREEN_H, g_rgb, 0 /* rotation */, true /* auto flush */,
        g_init_bus, GFX_NOT_DEFINED /* RST: on the expander */,
        st7701_type5_init_operations, sizeof(st7701_type5_init_operations));
    if (!g_gfx->begin()) {
        Serial.println("[board] gfx->begin() failed (PSRAM?)");
        return false;
    }
    // Elecrow: "Keep MADCTL's BGR bit set for this ST7701 panel".
    g_init_bus->beginWrite();
    g_init_bus->writeCommand(0x36);
    g_init_bus->write(0x08);
    g_init_bus->endWrite();
    g_gfx->fillScreen(0x0000);
    return true;
}
}  // namespace

void setBacklight(uint8_t level) {
    if (!g_bl_attached) {
        ledcAttach(pins::BACKLIGHT, pins::BACKLIGHT_HZ, pins::BACKLIGHT_BITS);
        g_bl_attached = true;
    }
    ledcWrite(pins::BACKLIGHT, level);
    g_backlight = level;
}

uint8_t backlight() { return g_backlight; }

Arduino_RGB_Display* boardGfx() { return g_gfx; }

// ------------------------------------------------------------------ touch
namespace {
Adafruit_CST8XX g_touch;

bool touchBegin() {
    // INT idles high; pulse RST low (Elecrow: high, low 120 ms, high).
    pcfWrite(pins::PCF_TOUCH_RST, true);
    delay(20);
    pcfWrite(pins::PCF_TOUCH_RST, false);
    delay(120);
    pcfWrite(pins::PCF_TOUCH_RST, true);
    delay(150);
    return g_touch.begin(&Wire, pins::TOUCH_ADDR);
}
}  // namespace

bool touchRead(int16_t& x, int16_t& y) {
    if (!g_status.touch) return false;
    if (!g_touch.touched()) return false;
    CST_TS_Point p = g_touch.getPoint(0);
    int px = p.x;
    int py = p.y + pins::TOUCH_Y_OFFSET;
    x = (int16_t)constrain(px, 0, SCREEN_W - 1);
    y = (int16_t)constrain(py, 0, SCREEN_H - 1);
    return true;
}

// ---------------------------------------------------------------- encoder
//
// Full quadrature decode on both edges of both channels. Contact bounce
// shows up as a back-and-forth pair of transitions and cancels out; invalid
// (double) jumps are ignored. Direction was settled on hardware by two other
// projects: an A edge with A != B is counter-clockwise, so the clockwise
// sequence is 00 → 01 → 11 → 10 → 00 in (A,B) order.
namespace {
volatile int32_t g_enc_raw = 0;
volatile int32_t g_enc_accum = 0;
volatile uint8_t g_enc_state = 0;
int32_t g_enc_detent_residual = 0;
portMUX_TYPE g_enc_mux = portMUX_INITIALIZER_UNLOCKED;

// Index = (prev << 2) | cur, value = +1 clockwise, -1 counter-clockwise.
const int8_t QDEC[16] = {
    0, +1, -1, 0,
   -1, 0, 0, +1,
   +1, 0, 0, -1,
    0, -1, +1, 0,
};

inline uint8_t IRAM_ATTR readAB() {
    // Direct register reads: the GPIO ISR service is installed IRAM-resident,
    // so this handler must not touch flash (digitalRead) while e.g. NVS is
    // writing. GPIO42 lives in the second input register.
    const uint32_t in0 = REG_READ(GPIO_IN_REG);
    const uint32_t in1 = REG_READ(GPIO_IN1_REG);
    const uint8_t a = (in1 >> (pins::ENC_A - 32)) & 1u;
    const uint8_t b = (in0 >> pins::ENC_B) & 1u;
    return (uint8_t)((a << 1) | b);
}

void IRAM_ATTR encIsr() {
    const uint8_t cur = readAB();
    portENTER_CRITICAL_ISR(&g_enc_mux);
    const uint8_t prev = g_enc_state;
    if (cur != prev) {
        // QDEC is laid out for (A,B) with clockwise 00→01→11→10.
        const int8_t d = QDEC[(prev << 2) | cur];
        g_enc_state = cur;
        g_enc_raw += d;
        g_enc_accum += d;
    }
    portEXIT_CRITICAL_ISR(&g_enc_mux);
}

void encoderBegin() {
    pinMode(pins::ENC_A, INPUT_PULLUP);
    pinMode(pins::ENC_B, INPUT_PULLUP);
    g_enc_state = readAB();
    attachInterrupt(digitalPinToInterrupt(pins::ENC_A), encIsr, CHANGE);
    attachInterrupt(digitalPinToInterrupt(pins::ENC_B), encIsr, CHANGE);
}
}  // namespace

int32_t encoderTakeDetents() {
    portENTER_CRITICAL(&g_enc_mux);
    const int32_t acc = g_enc_accum;
    g_enc_accum = 0;
    portEXIT_CRITICAL(&g_enc_mux);
    g_enc_detent_residual += acc;
    const int32_t det = g_enc_detent_residual / KNOB_TRANSITIONS_PER_DETENT;
    g_enc_detent_residual -= det * KNOB_TRANSITIONS_PER_DETENT;
    return det;
}

int32_t encoderRawCount() { return g_enc_raw; }

// ----------------------------------------------------------------- button
bool buttonPoll(uint32_t now, bool& down) {
    static uint32_t last_poll = 0;
    static bool raw = false, stable = false;
    static uint32_t raw_changed = 0;
    if (!g_status.expander) return false;
    if (now - last_poll < 8) return false;
    last_poll = now;
    const int port = pcfReadPort();
    if (port < 0) return false;
    const bool d = !(port & (1u << pins::PCF_ENC_SW));   // active low
    if (d != raw) { raw = d; raw_changed = now; }
    if (raw != stable && now - raw_changed >= 25) {
        stable = raw;
        down = stable;
        return true;
    }
    return false;
}

// ------------------------------------------------------------------ begin
BoardStatus boardBegin() {
    g_status.psram = psramFound();
    Serial.printf("[board] PSRAM %u bytes, free heap %u\n",
                  (unsigned)ESP.getPsramSize(), (unsigned)ESP.getFreeHeap());

    Wire.begin(pins::I2C_SDA, pins::I2C_SCL, pins::I2C_HZ);
    Wire.beginTransmission(pins::PCF8574_ADDR);
    g_status.expander = (Wire.endTransmission() == 0);
    if (g_status.expander) {
        g_pcf_shadow = 0xFF;
        pcfFlush();
        Serial.printf("[board] PCF8574 ok @0x%02X\n", pins::PCF8574_ADDR);
        panelPowerCycle();
    } else {
        Serial.printf("[board] PCF8574 missing @0x%02X — panel power/reset "
                      "and the knob switch are unreachable\n", pins::PCF8574_ADDR);
    }

    g_status.panel = panelBegin();
    Serial.printf("[board] panel %s\n", g_status.panel ? "ok" : "FAIL");
    setBacklight(204);

    if (g_status.expander) {
        g_status.touch = touchBegin();
    }
    Serial.printf("[board] touch %s @0x%02X\n",
                  g_status.touch ? "ok" : "missing", pins::TOUCH_ADDR);

    encoderBegin();
    Serial.printf("[board] encoder A=%d B=%d, switch on PCF P%d\n",
                  pins::ENC_A, pins::ENC_B, pins::PCF_ENC_SW);
    return g_status;
}

const BoardStatus& boardStatus() { return g_status; }

}  // namespace knob
