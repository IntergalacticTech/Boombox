#pragma once
#include <Arduino.h>

namespace boombox {

struct BoomboxState;  // forward — defined in state/BoomboxState.h

// Implemented by each profile's UI layer (LVGL for CYD; no-op for headless).
// The shared core's app-loop drives tick() and routes state-change pushes
// to onStateUpdate().
class IUI {
public:
    virtual ~IUI() = default;
    virtual void init() = 0;
    virtual void tick(uint32_t millis_now) = 0;
    virtual void onStateUpdate(const BoomboxState& s) = 0;
    virtual void enterAmbient() = 0;
    virtual void exitAmbient() = 0;
};

} // namespace boombox
