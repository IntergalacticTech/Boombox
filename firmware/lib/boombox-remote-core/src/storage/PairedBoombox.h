#pragma once
#include <Arduino.h>

namespace boombox {

struct PairedBoombox {
    String id;
    String name;
    String auth_token;
    uint32_t paired_at;     // epoch seconds
};

// NVS-backed store for the boombox this remote is paired with. Phase 2
// MVP supports one paired boombox; multi-pair switcher comes later.
class PairedBoomboxStore {
public:
    static bool load(PairedBoombox& out);
    static bool save(const PairedBoombox& pb);
    static void clear();
    static bool isPaired();
};

} // namespace boombox
