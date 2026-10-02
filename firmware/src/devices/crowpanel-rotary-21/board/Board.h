// Board layer for the Elecrow CrowPanel 2.1" ESP32-S3 rotary display.
//
// Pin map and panel timings are transcribed from Elecrow's reference sketch
// for this exact board:
//   github.com/Elecrow-RD/CrowPanel-2.1inch-HMI-ESP32-Rotary-Display-480-480-
//   IPS-Round-Touch-Knob-Screen  →  example/Arduino/RotaryScreen_2_1/
//   RotaryScreen_2_1.ino
// and cross-checked against two independent working projects on the same
// board (mkvesala/ESP32-Crowpanel-compass, gurul/spotify-knob).
//
// NOT followed: Elecrow's "Simple example/Encoder_code" (A=45 B=42 SW=41) and
// "Simple example/RGB_CODE" (WS2812 on GPIO48). Both contradict the main
// sketch — GPIO45/48 are panel data lines here — and belong to another board.
#pragma once
#include <Arduino.h>

class Arduino_RGB_Display;

namespace knob {

namespace pins {
// I2C bus shared by the PCF8574 expander and the CST8xx touch controller.
constexpr int I2C_SDA = 38;
constexpr int I2C_SCL = 39;
constexpr uint32_t I2C_HZ = 400000;

// PCF8574 I/O expander. LCD power + reset hang off it, so the panel cannot be
// brought up over GPIO alone.
constexpr uint8_t PCF8574_ADDR  = 0x21;
constexpr uint8_t PCF_TOUCH_RST = 0;   // P0
constexpr uint8_t PCF_TOUCH_INT = 2;   // P2 (held high)
constexpr uint8_t PCF_LCD_POWER = 3;   // P3
constexpr uint8_t PCF_LCD_RESET = 4;   // P4, active low
constexpr uint8_t PCF_ENC_SW    = 5;   // P5, input, active low

// CST8xx capacitive touch.
constexpr uint8_t TOUCH_ADDR = 0x15;
// Elecrow's sketch shifts touch Y up by 20 px to line up with the glass.
constexpr int TOUCH_Y_OFFSET = -20;

// Quadrature encoder — both channels are real GPIO.
constexpr int ENC_A = 42;
constexpr int ENC_B = 4;

// Backlight PWM.
constexpr int BACKLIGHT = 6;
constexpr uint32_t BACKLIGHT_HZ = 5000;
constexpr uint8_t BACKLIGHT_BITS = 8;

// ST7701S: 3-wire SPI for the init sequence only, then RGB565 parallel.
constexpr int LCD_CS = 16, LCD_SCK = 2, LCD_SDA = 1;
constexpr int LCD_DE = 40, LCD_VSYNC = 7, LCD_HSYNC = 15, LCD_PCLK = 41;
constexpr int LCD_R0 = 46, LCD_R1 = 3,  LCD_R2 = 8,  LCD_R3 = 18, LCD_R4 = 17;
constexpr int LCD_G0 = 14, LCD_G1 = 13, LCD_G2 = 12, LCD_G3 = 11, LCD_G4 = 10, LCD_G5 = 9;
constexpr int LCD_B0 = 5,  LCD_B1 = 45, LCD_B2 = 48, LCD_B3 = 47, LCD_B4 = 21;
}  // namespace pins

constexpr int SCREEN_W = 480;
constexpr int SCREEN_H = 480;

// Encoder quadrature transitions per mechanical detent. Elecrow's sketch
// counts one step per rising edge of A, i.e. one full quadrature cycle (four
// transitions) per detent. If a physical click moves the volume by two steps
// (or needs two clicks for one step), change this to 2 (or 8).
#ifndef KNOB_TRANSITIONS_PER_DETENT
#define KNOB_TRANSITIONS_PER_DETENT 4
#endif

struct BoardStatus {
    bool expander = false;
    bool panel = false;
    bool touch = false;
    bool psram = false;
};

// Bring up expander → panel power/reset → ST7701 + RGB → backlight → touch →
// encoder. Each piece is independent: a missing expander or touch chip is
// logged and the rest still runs.
BoardStatus boardBegin();
const BoardStatus& boardStatus();

Arduino_RGB_Display* boardGfx();

void    setBacklight(uint8_t level);   // 0-255
uint8_t backlight();

// Touch: true while a finger is down; x/y in screen coordinates.
bool touchRead(int16_t& x, int16_t& y);

// Encoder: signed detents since the last call (clockwise positive).
int32_t encoderTakeDetents();
// Raw quadrature transition counter since boot (diagnostics).
int32_t encoderRawCount();

// Encoder push switch (debounced, sampled from the expander). Call
// buttonPoll() from the loop; it returns true when the debounced level
// changed, with `down` set to the new level.
bool buttonPoll(uint32_t now_ms, bool& down);

}  // namespace knob
