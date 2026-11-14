// lv_conf.h for the crowpanel-rotary-21 profile (LVGL 9, 480x480 RGB panel).
//
// Shadows firmware/src/lv_conf.h: this directory is first on the include
// path for this env only. Differences from the CYD config:
//   * libc malloc — on the S3 with octal PSRAM, large allocations (snapshot
//     buffers, big label caches) fall through to PSRAM automatically instead
//     of exhausting a fixed LVGL pool.
//   * lv_snapshot enabled — the `snap` serial command streams the screen.
//   * larger Montserrat sizes for a 2.1" face viewed at arm's length.

#ifndef LV_CONF_H
#define LV_CONF_H

#define LV_COLOR_DEPTH 16

#define LV_USE_STDLIB_MALLOC  LV_STDLIB_CLIB
#define LV_USE_STDLIB_STRING  LV_STDLIB_CLIB
#define LV_USE_STDLIB_SPRINTF LV_STDLIB_CLIB

#define LV_DEF_REFR_PERIOD 20
#define LV_USE_OS LV_OS_NONE

#define LV_DRAW_SW_COMPLEX 1
#define LV_USE_DRAW_SW 1
#define LV_DRAW_SW_SHADOW_CACHE_SIZE 0
#define LV_DRAW_SW_CIRCLE_CACHE_SIZE 8

#define LV_USE_LOG 0

#define LV_USE_LABEL 1
#define LV_LABEL_TEXT_SELECTION 0
#define LV_LABEL_LONG_TXT_HINT 1
#define LV_USE_BUTTON 1
#define LV_USE_IMAGE 1
#define LV_USE_LINE 1
#define LV_USE_ARC 1
#define LV_USE_SLIDER 0
#define LV_USE_TEXTAREA 1
#define LV_USE_SPINBOX 0
#define LV_USE_KEYBOARD 0
#define LV_USE_LIST 0
#define LV_USE_SPINNER 1
#define LV_USE_SCALE 0
#define LV_USE_BAR 1
#define LV_USE_BUTTONMATRIX 0
#define LV_USE_CANVAS 0
#define LV_USE_CHECKBOX 0
#define LV_USE_DROPDOWN 0
#define LV_USE_ROLLER 0
#define LV_USE_SWITCH 0
#define LV_USE_TABLE 0
#define LV_USE_TABVIEW 0
#define LV_USE_WINDOW 0
#define LV_USE_TILEVIEW 0
#define LV_USE_MSGBOX 0
#define LV_USE_CALENDAR 0
#define LV_USE_CHART 0
#define LV_USE_LED 0
#define LV_USE_MENU 0
#define LV_USE_SPAN 0
#define LV_USE_ANIMIMG 0
#define LV_USE_IMAGEBUTTON 0

#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_24 1
#define LV_FONT_MONTSERRAT_28 1
#define LV_FONT_MONTSERRAT_32 1
#define LV_FONT_MONTSERRAT_40 1
#define LV_FONT_MONTSERRAT_48 1
#define LV_FONT_DEFAULT &lv_font_montserrat_20
#define LV_USE_FONT_PLACEHOLDER 1

#define LV_USE_THEME_DEFAULT 1
#define LV_THEME_DEFAULT_DARK 1
#define LV_USE_THEME_SIMPLE 0
#define LV_USE_THEME_MONO 0

#define LV_USE_SNAPSHOT 1

#define LV_INDEV_DEF_READ_PERIOD 20

#endif // LV_CONF_H
