#pragma once
#include <lvgl.h>

namespace boombox::theme {

// Colors — matches the kiosk PairOverlay tokens so the experience feels
// like the same product across boombox + remote.
inline const lv_color_t BG_DARK   = lv_color_make(20, 20, 28);
inline const lv_color_t FG_TEXT   = lv_color_make(240, 240, 245);
inline const lv_color_t MUTED     = lv_color_make(140, 140, 150);
inline const lv_color_t ACCENT    = lv_color_make(79, 195, 247);   // cyan
inline const lv_color_t BUTTON_BG = lv_color_make(40, 40, 50);
inline const lv_color_t WARN      = lv_color_make(244, 143, 177);

// Apply base styles to the active screen.
void applyScreen(lv_obj_t* scr);

// Force-load a screen and synchronously flush the display. Helps after
// BLE operations leave LVGL in a state where the lazy timer-handler tick
// doesn't actually push pixels to the panel.
void loadAndRefresh(lv_obj_t* scr);

// Clear all children from the active screen and reapply base styles.
// Use this instead of creating a new screen + lv_screen_load — that path
// has rendering issues after blocking BLE operations.
void resetActiveScreen();

// Big touch-target button. Returns the button; the caller can attach
// an event handler.
lv_obj_t* makeButton(lv_obj_t* parent, const char* label, int w, int h);

// Title row at the top of a screen.
lv_obj_t* makeTitle(lv_obj_t* parent, const char* text);

} // namespace boombox::theme
