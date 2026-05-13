#include "PairedBoombox.h"
#include <Preferences.h>

namespace boombox {

static constexpr const char* NS = "paired";

bool PairedBoomboxStore::load(PairedBoombox& out) {
    Preferences p;
    if (!p.begin(NS, true)) return false;
    out.id         = p.getString("id", "");
    out.name       = p.getString("name", "");
    out.auth_token = p.getString("token", "");
    out.paired_at  = p.getUInt("paired_at", 0);
    p.end();
    return out.auth_token.length() > 0;
}

bool PairedBoomboxStore::save(const PairedBoombox& pb) {
    Preferences p;
    if (!p.begin(NS, false)) return false;
    p.putString("id", pb.id);
    p.putString("name", pb.name);
    p.putString("token", pb.auth_token);
    p.putUInt("paired_at", pb.paired_at);
    p.end();
    return true;
}

void PairedBoomboxStore::clear() {
    Preferences p;
    if (!p.begin(NS, false)) return;
    p.clear();
    p.end();
}

bool PairedBoomboxStore::isPaired() {
    PairedBoombox tmp;
    return load(tmp);
}

} // namespace boombox
