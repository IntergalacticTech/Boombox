#pragma once
// Volume step per knob detent, accelerated by turn speed: a slow click is a
// fine 4 % step; a quick spin covers the range in well under one turn.
#include <stdint.h>

namespace knob {

// `gap_ms` = time since the previous detent (UINT32_MAX for the first one).
inline int volumeStepForGap(uint32_t gap_ms) {
    if (gap_ms < 45)  return 10;
    if (gap_ms < 110) return 6;
    return 4;
}

}  // namespace knob
