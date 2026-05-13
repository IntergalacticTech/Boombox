#pragma once
#include <Arduino.h>

namespace boombox {

// Capabilities a device profile declares. Drives feature flags in the
// shared core (e.g. ambient mode is skipped on profiles without a
// display; volume-gesture handling is touch-only).
struct DeviceCapabilities {
    bool has_display;
    bool has_touch;
    bool has_ldr;        // ambient light sensor
    bool has_rgb_led;
};

// Implemented by each profile's device shell. The shared core calls these
// from the main loop and at boot.
class IDevice {
public:
    virtual ~IDevice() = default;
    virtual void init() = 0;
    virtual void pollInputs() = 0;
    virtual void setBrightness(uint8_t pct) = 0;  // 0-100, no-op without display
    virtual uint16_t readLdr() = 0;               // 0-4095, 0 without LDR
    virtual DeviceCapabilities caps() const = 0;
};

} // namespace boombox
