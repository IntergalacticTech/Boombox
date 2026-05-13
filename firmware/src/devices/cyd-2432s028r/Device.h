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
};

} // namespace boombox
