#include "Theme.h"
#include <Arduino.h>  // for delay()

namespace boombox::theme {

void applyScreen(lv_obj_t* scr) {
    lv_obj_set_style_bg_color(scr, BG_DARK, 0);
    lv_obj_set_style_text_color(scr, FG_TEXT, 0);
    lv_obj_set_style_pad_all(scr, 0, 0);
}

void loadAndRefresh(lv_obj_t* scr) {
    lv_screen_load(scr);
    lv_obj_invalidate(scr);
    for (int i = 0; i < 6; i++) { lv_timer_handler(); delay(8); }
}

void resetActiveScreen() {
    lv_obj_t* scr = lv_screen_active();
    lv_obj_clean(scr);                       // remove all children
    applyScreen(scr);
    lv_obj_invalidate(scr);
    for (int i = 0; i < 6; i++) { lv_timer_handler(); delay(8); }
}

lv_obj_t* makeButton(lv_obj_t* parent, const char* label, int w, int h) {
    lv_obj_t* btn = lv_button_create(parent);
    lv_obj_set_size(btn, w, h);
    lv_obj_set_style_bg_color(btn, ACCENT, 0);
    // Visible "pushed" feedback. LVGL toggles LV_STATE_PRESSED while a
    // finger is down — this selector overrides the bg color in that state.
    lv_obj_set_style_bg_color(btn, ACCENT_PRESSED, LV_STATE_PRESSED);
    // A subtle inward translation reinforces the "press" feel without
    // needing animations.
    lv_obj_set_style_translate_y(btn, 2, LV_STATE_PRESSED);
    lv_obj_set_style_text_color(btn, lv_color_make(0, 0, 0), 0);
    lv_obj_set_style_radius(btn, 10, 0);
    lv_obj_set_style_border_width(btn, 0, 0);
    lv_obj_t* l = lv_label_create(btn);
    lv_label_set_text(l, label);
    lv_obj_set_style_text_font(l, &lv_font_montserrat_20, 0);
    lv_obj_center(l);
    return btn;
}

lv_obj_t* makeTitle(lv_obj_t* parent, const char* text) {
    lv_obj_t* l = lv_label_create(parent);
    lv_label_set_text(l, text);
    lv_obj_set_style_text_font(l, &lv_font_montserrat_20, 0);
    lv_obj_set_style_text_color(l, FG_TEXT, 0);
    lv_obj_align(l, LV_ALIGN_TOP_MID, 0, 12);
    return l;
}

} // namespace boombox::theme
