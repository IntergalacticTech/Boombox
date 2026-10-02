#include "VolumeCoalescer.h"

namespace knob {

static int clamp100(int v) { return v < 0 ? 0 : (v > 100 ? 100 : v); }

bool VolumeCoalescer::adjusting(uint32_t now) const {
    return _dirty || (_ever_turned && now - _last_turn < _settle);
}

int VolumeCoalescer::turn(int delta, int step, uint32_t now) {
    const int base = adjusting(now) || _reported < 0 ? _target : _reported;
    _target = clamp100(base + delta * step);
    _dirty = true;
    _ever_turned = true;
    _last_turn = now;
    return _target;
}

void VolumeCoalescer::reported(int v, uint32_t now) {
    if (v < 0) return;
    _reported = clamp100(v);
    if (!adjusting(now)) _target = _reported;
}

int VolumeCoalescer::pollSend(uint32_t now) {
    if (!_dirty) return -1;
    if (_ever_sent && now - _last_sent < _min_interval) return -1;
    _dirty = false;
    _ever_sent = true;
    _last_sent = now;
    return _target;
}

int VolumeCoalescer::displayed(uint32_t now) const {
    if (adjusting(now) || _reported < 0) return _target;
    return _reported;
}

}  // namespace knob
