// Minimal lv_conf.h for LVGL 9 on ESP32 + 240x320 ILI9341.
// Picked from LVGL 9.x's reference template; trimmed to what this project
// actually uses. Feature toggles default to off; we enable explicitly.

#ifndef LV_CONF_H
#define LV_CONF_H

// ---------- 1. COLOR ----------
#define LV_COLOR_DEPTH 16

// ---------- 2. MEMORY ----------
#define LV_USE_STDLIB_MALLOC LV_STDLIB_BUILTIN
#define LV_MEM_SIZE (48 * 1024U)   // 48 KB heap for LVGL objects
#define LV_USE_STDLIB_STRING LV_STDLIB_BUILTIN
#define LV_USE_STDLIB_SPRINTF LV_STDLIB_BUILTIN

// ---------- 3. HAL ----------
#define LV_DEF_REFR_PERIOD 16      // ~60 fps
#define LV_TICK_CUSTOM 0           // we call lv_tick_inc() ourselves, no — use built-in millis based via lv_tick_get
#define LV_USE_OS LV_OS_NONE

// ---------- 4. RENDERING ----------
#define LV_DRAW_SW_COMPLEX 1
#define LV_USE_DRAW_SW 1

// ---------- 5. LOGGING ----------
#define LV_USE_LOG 0

// ---------- 6. WIDGETS ----------
#define LV_USE_LABEL 1
#define LV_LABEL_TEXT_SELECTION 0
#define LV_LABEL_LONG_TXT_HINT 1
#define LV_USE_BUTTON 1
#define LV_USE_IMAGE 1
#define LV_USE_LINE 1
#define LV_USE_ARC 1
#define LV_USE_SLIDER 1
#define LV_USE_TEXTAREA 1
#define LV_USE_KEYBOARD 1
#define LV_USE_LIST 1
#define LV_USE_SPINNER 1
#define LV_USE_SCALE 0
#define LV_USE_BAR 1
#define LV_USE_BUTTONMATRIX 1
#define LV_USE_CANVAS 1
#define LV_USE_CHECKBOX 0
#define LV_USE_DROPDOWN 0
#define LV_USE_ROLLER 0
#define LV_USE_SWITCH 1
#define LV_USE_TABLE 0
#define LV_USE_TABVIEW 0
#define LV_USE_WINDOW 0
#define LV_USE_TILEVIEW 0
#define LV_USE_MSGBOX 0
#define LV_USE_CALENDAR 0
#define LV_USE_CHART 0
#define LV_USE_LED 0
#define LV_USE_MENU 0
#define LV_USE_METER 0

// ---------- 7. FONTS ----------
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_24 1
#define LV_FONT_MONTSERRAT_28 1
#define LV_FONT_DEFAULT &lv_font_montserrat_16
#define LV_FONT_FMT_TXT_LARGE 0
#define LV_USE_FONT_PLACEHOLDER 1

// ---------- 8. THEMES ----------
#define LV_USE_THEME_DEFAULT 1
#define LV_THEME_DEFAULT_DARK 1
#define LV_USE_THEME_SIMPLE 0
#define LV_USE_THEME_MONO 0

// ---------- 9. INDEV ----------
#define LV_INDEV_DEF_READ_PERIOD 30

#endif // LV_CONF_H
