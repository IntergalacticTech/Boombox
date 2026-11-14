#pragma once
// The knob's screen follows the boombox:
//   * boombox playing          → Awake (full brightness, showing the track)
//   * boombox awake, not playing → Awake for DIM_AFTER_MS after the last
//                                  input, then Dim — never Off, because the
//                                  boombox itself is awake
//   * boombox asleep           → Off (an input lights it for DIM_AFTER_MS)
//   * no state / link down     → input timers: Dim at DIM_AFTER_MS, Off at
//                                OFF_AFTER_MS, so a disconnected knob doesn't
//                                glow forever
// KnobApp applies the result every tick; the "first input after Dim/Off only
// wakes the screen" rule and the self-wake on asleep→awake / play edges live
// there (they reset ms_since_input).
//
// Pure logic, unit-tested natively.
#include <stdint.h>

namespace knob {

enum class Screen : uint8_t { Awake, Dim, Off };

constexpr uint32_t SCREEN_DIM_AFTER_MS = 30000;
constexpr uint32_t SCREEN_OFF_AFTER_MS = 120000;

inline Screen screenPolicy(bool have_state, bool playing, bool boombox_asleep,
                           uint32_t ms_since_input) {
    const bool recent = ms_since_input <= SCREEN_DIM_AFTER_MS;
    if (!have_state) {
        if (recent) return Screen::Awake;
        return ms_since_input <= SCREEN_OFF_AFTER_MS ? Screen::Dim : Screen::Off;
    }
    if (boombox_asleep) return recent ? Screen::Awake : Screen::Off;
    if (playing) return Screen::Awake;
    return recent ? Screen::Awake : Screen::Dim;
}

inline const char* screenName(Screen s) {
    return s == Screen::Awake ? "awake" : s == Screen::Dim ? "dim" : "off";
}

}  // namespace knob
