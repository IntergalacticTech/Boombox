#pragma once
#include "device/IDevice.h"

namespace boombox {

class CydDevice : public IDevice {
public:
    void init() override;
    void pollInputs() override;
    void setBrightness(uint8_t pct) override;
    uint16_t readLdr() override;
    DeviceCapabilities caps() const override;

    // Diagnostic: paint a solid color directly via TFT_eSPI, bypassing
    // LVGL. Used to verify the display bus is alive after BLE init.
    void paintSolid(uint16_t color565);
};

} // namespace boombox
