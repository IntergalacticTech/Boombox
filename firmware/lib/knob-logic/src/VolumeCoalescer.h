// Optimistic, rate-limited volume control for the knob.
//
// Turning the knob moves a local target at once (the arc follows the hand).
// Absolute `volume` commands go out at most once per `min_interval_ms`, and
// the final value is always sent. About `settle_ms` after the last turn the
// displayed value goes back to whatever the boombox reports, so the arc
// settles on the truth if a command was lost or clamped.
//
// Pure logic, unit-tested natively.
#pragma once
#include <stdint.h>

namespace knob {

class VolumeCoalescer {
public:
    explicit VolumeCoalescer(uint32_t min_interval_ms = 125,
                             uint32_t settle_ms = 1000)
        : _min_interval(min_interval_ms), _settle(settle_ms) {}

    // The knob moved `delta` steps of `step` percent. Returns the new target.
    int turn(int delta, int step, uint32_t now);

    // The boombox reported its volume (0-100, or <0 for unknown).
    void reported(int v, uint32_t now);

    // Value to send now, or -1 if nothing is due.
    int pollSend(uint32_t now);

    // What the arc should show right now.
    int displayed(uint32_t now) const;

    // True while the user's own value overrides the reported one.
    bool adjusting(uint32_t now) const;

    int reportedValue() const { return _reported; }

private:
    uint32_t _min_interval;
    uint32_t _settle;
    int _target = 0;
    int _reported = -1;
    bool _dirty = false;
    bool _ever_turned = false;
    bool _ever_sent = false;
    uint32_t _last_turn = 0;
    uint32_t _last_sent = 0;
};

}  // namespace knob
