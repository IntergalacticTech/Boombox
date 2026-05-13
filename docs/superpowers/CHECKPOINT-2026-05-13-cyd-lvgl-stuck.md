# Checkpoint — CYD firmware: LVGL screens won't render after BLE ops

Date: 2026-05-13
Status: blocked — handing off to a fresh context window

## TL;DR

Phase 2 firmware boots, finds the boombox over BLE, connects to all
five GATT characteristics, and prints success to serial. But **the LVGL
display stays frozen on the first screen rendered before the first BLE
operation**. Every subsequent screen transition fails to push pixels to
the panel even though the firmware logic completes correctly.

Pi-side is fully working (HTTP + WS + BLE peripheral + PairOverlay
kiosk UI). The wall is purely on the CYD firmware's display pipeline.

## What's working

| Component | State |
|---|---|
| Pi `boombox-remote.py` service | ✅ running on :6685, mDNS, REST + WS |
| Pi BLE GATT peripheral (`bless`) | ✅ advertising `0000bbbb-...` with name "Boombox" |
| Pi-side PIN endpoints (`/pair/start`, `/pair`) | ✅ tested via curl |
| Kiosk PairOverlay UI | ✅ shows 6-digit PIN on tap |
| Kiosk touch UX (big scrollbar, nudge buttons, dismissable player) | ✅ |
| CYD firmware build (PlatformIO + Arduino-ESP32 + LVGL 9.5) | ✅ |
| CYD vendor-correct display config (HSPI port, ST7789, BGR order, 80 MHz) | ✅ — first screen renders perfectly |
| NimBLE-Arduino central on CYD | ✅ async scan finds Boombox at -49 dBm |
| BLE connect + GATT discovery on CYD | ✅ all 5 chars resolved |
| `pi-flash` helper script | ✅ build → rsync → esptool on the Pi |

Serial output proves the firmware fully exercises the BLE chain:

```
[boot] device + UI ready
[boot] BLE central initialized
[loop] starting BLE scan
[ble] async-scan hit 'Boombox' 88:a2:9e:43:b7:8a
[loop] connecting to 88:a2:9e:43:b7:8a
[ble] connected; discovered chars
[loop] connected; showing pair screen
```

## The bug

After the firmware reaches the `[loop] connected` log line, it calls
`SingleScreen::showPair(...)` which toggles visibility of a pre-built
"PAIR" group of LVGL widgets. The serial confirms the code runs. The
panel stays on whatever was rendered before the BLE ops — the
"Looking for a boombox" message.

The same symptom occurred with every architecture we tried:
- New screens via `lv_obj_create(nullptr)` + `lv_screen_load`
- `lv_obj_clean(lv_screen_active())` + rebuild on the same screen
- Dedicated FreeRTOS LVGL task (caused blank-white before settings change)
- Pre-built widgets toggled via `LV_OBJ_FLAG_HIDDEN` (current code)

A direct `_tft.fillScreen(0x001F)` call from the main task immediately
after BLE *does* show on the panel as blue, and stays blue. So:
- The TFT bus is alive post-BLE ✅
- LVGL widget tree updates are happening (no crashes) ✅
- **LVGL's flush callback is not pushing the updated tree to the panel** ❌

## Things tried (chronological, dead ends)

1. **Display driver swap**: ILI9341 → ST7789 → fixed initial rendering.
   The panel ships ST7789 even though the AITRIP CYD listing references
   ILI9341 (vendor confirmed via `Freenove_ESP32_Display-main` docs).

2. **Color order**: `TFT_RGB_ORDER=TFT_BGR` per vendor User_Setup.

3. **SPI port**: `USE_HSPI_PORT=1` (CRITICAL — without this the touch
   SPI on VSPI and the TFT SPI defaulting to VSPI conflict; this is what
   gave us the first correctly-rendered screen). Vendor canonical pin
   map from `tft_setups/TFT_eSPI_Setups/FNK0103B_2.8_240x320_ST7789.h`.

4. **SPI clock**: bumped to 80 MHz per vendor.

5. **CPU lock**: `setCpuFrequencyMhz(240)` at boot to keep BLE from
   shifting APB clock during the scan and possibly desyncing the TFT.

6. **`LV_COLOR_16_SWAP 1`**: enabled, then disabled — vendor doesn't use
   it; with `TFT_RGB_ORDER=TFT_BGR` + the swap flag on `pushColors(...,
   true)`, colors come out correct.

7. **`LV_USE_OS LV_OS_FREERTOS`**: failed to compile (LVGL 9 needs
   `atomic.h` which Arduino-ESP32 doesn't ship).

8. **Dedicated LVGL task** (`xTaskCreatePinnedToCore`): introduced
   blank-white screen — multi-task LVGL needs proper locking which we
   can't get without LV_OS_FREERTOS.

9. **Deferred screen destruction** (use-after-free fix): moved screen
   delete to the main loop after callbacks complete. Serial confirms
   transitions fire; pixels still don't update.

10. **`lv_obj_invalidate` + multiple `lv_timer_handler` ticks** after
    every `lv_screen_load`: no effect.

11. **Skip screen swap entirely, reuse `lv_screen_active()`**: also
    failed to render — `lv_obj_clean(scr)` left things blank.

12. **Single-screen state machine with hidden groups**: present approach.
    Pre-build all UI, toggle `LV_OBJ_FLAG_HIDDEN`. STILL fails.

## Hypotheses to investigate fresh

Order by suspicion:

1. **LVGL `lv_timer_handler` is being called but the flush callback
   isn't actually being invoked post-BLE.** Could verify by adding a
   `Serial.printf` inside `Device.cpp`'s `_flush()` and counting calls
   before vs after BLE. If flushes drop to zero, the issue is upstream
   in LVGL's refresh scheduling.

2. **NimBLE's BLE host task is running on core 1 (same as Arduino loop)
   at a high priority** and starving the Arduino task. Even though we
   call `lv_timer_handler()`, it gets preempted before the flush
   completes. Workaround: pin NimBLE to core 0 explicitly (call
   `NimBLEDevice::setPower(..., ESP_BLE_PWR_TYPE_DEFAULT)` and check the
   `BT_CONTROLLER_TASK_CORE` option), or run LVGL on its own task with
   a higher priority than NimBLE host.

3. **LVGL's display buffer is in DRAM** that the BLE controller stomps
   on. We use `lv_color_t _draw_buf[240 * 40]` as a file-scope static
   — that's 19.2 KB. ESP32 BLE controller likes the bottom of DRAM.
   Move to PSRAM if available (no PSRAM on this CYD), or shrink the
   buffer and place explicitly via `DRAM_ATTR`.

4. **Switch to ESP-IDF or LovyanGFX.** The Freenove example
   `Sketch_19.1_LVGL_Arduino.ino` uses LVGL 8.4 (bundled in
   `Libraries/lvgl_v8.4.0.zip`) not 9.x. LVGL 8.4 has a simpler
   threading model and the vendor's sketches presumably work on this
   exact hardware. Trying LVGL 8.4 would isolate "is this LVGL 9.x
   regression on ESP32-Arduino".

5. **TFT_eSPI's transaction lock.** With BLE host running, ESP32 SPI
   transactions get serialized via `SUPPORT_TRANSACTIONS`. Maybe
   transactions aren't being acquired/released properly after a BLE
   scan disrupts them. Force-enable `-D SUPPORT_TRANSACTIONS=1`.

6. **Reset the TFT after BLE init.** Call `_tft.init()` again after
   `NimBLEDevice::init()`. Crude but a useful binary signal.

## Files of interest

- `firmware/platformio.ini` — vendor-canonical TFT_eSPI config (HSPI, ST7789, BGR, 80 MHz)
- `firmware/src/lv_conf.h` — LVGL 9 config (LV_USE_OS NONE)
- `firmware/src/devices/cyd-2432s028r/Device.cpp` — `_flush()` cb is here; add `Serial.printf` to count invocations
- `firmware/src/devices/cyd-2432s028r/main.cpp` — boot state machine
- `firmware/src/devices/cyd-2432s028r/ui/SingleScreen.cpp` — current single-screen UI
- `firmware/lib/boombox-remote-core/src/transport/BleClient.cpp` — NimBLE central
- `services/ble_peripheral.py` — Pi-side BLE GATT (Pi is fine, just for context)
- `Freenove_ESP32_Display-main/Sketches/Sketch_19.1_LVGL_Arduino/` — vendor's LVGL 8.4 reference sketch

## Smoking-gun diagnostic to try first in fresh context

Drop this into `Device.cpp:_flush()`:

```cpp
static void _flush(lv_display_t* disp, const lv_area_t* area, uint8_t* px) {
    static uint32_t calls = 0; static uint32_t last_log = 0;
    if (++calls && (millis() - last_log > 1000)) {
        Serial.printf("[flush] %u total calls\n", calls);
        last_log = millis();
    }
    // ... rest of the flush ...
}
```

If `[flush]` lines stop after the first BLE op, the issue is LVGL's
refresh scheduler. If they keep arriving but the display doesn't update,
the issue is the SPI bus or TFT_eSPI.

## How to resume

Worktree: `/Users/jwc/code/Boombox/.claude/worktrees/wireless-remote`
Branch: `worktree-wireless-remote` (PR #1)
Pi target: `ssh boombox` (config in `~/.ssh/config` → 192.168.1.176)
Flash command: `cd firmware && ./pi-flash --no-build` (build flag if needed)
Serial: `ssh boombox 'cat /dev/ttyUSB0'` won't reset; the included
python serial-with-DTR helper in earlier captures does a clean reset.
