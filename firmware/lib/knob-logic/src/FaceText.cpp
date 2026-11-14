#include "FaceText.h"

#include <cctype>
#include <cstring>

namespace knob {

namespace {

struct Src {
    const char* id;
    const char* caption;
    const char* name;
};
const Src SRCS[] = {
    {"mopidy", "LIBRARY", "Library"},
    {"airplay", "AIRPLAY", "AirPlay"},
    {"spotify", "SPOTIFY", "Spotify"},
    {"bluetooth", "BLUETOOTH", "Bluetooth"},
    {"movies", "VIDEO", "Video"},
};

const Src* find(const char* id) {
    if (!id || !*id) return nullptr;
    for (const Src& s : SRCS)
        if (std::strcmp(s.id, id) == 0) return &s;
    return nullptr;
}

std::string upper(const char* s) {
    std::string out(s ? s : "");
    for (char& c : out) c = (char)std::toupper((unsigned char)c);
    return out;
}

// A source's display name for a headline ("Bluetooth"), or its raw id.
std::string friendlyName(const char* id) {
    const Src* s = find(id);
    return s ? s->name : std::string(id ? id : "");
}

bool empty(const char* s) { return !s || !*s; }

// "S01E02", "s1e2", "S1:E2", "S1 E2" anywhere in `s`.
bool hasEpisodeMarker(const std::string& s) {
    for (size_t i = 0; i < s.size(); i++) {
        if (s[i] != 'S' && s[i] != 's') continue;
        if (i > 0 && std::isalnum((unsigned char)s[i - 1])) continue;
        size_t j = i + 1, d = 0;
        while (j < s.size() && std::isdigit((unsigned char)s[j])) { j++; d++; }
        if (!d) continue;
        if (j < s.size() && (s[j] == ':' || s[j] == ' ')) j++;
        if (j >= s.size() || (s[j] != 'E' && s[j] != 'e')) continue;
        j++;
        if (j < s.size() && std::isdigit((unsigned char)s[j])) return true;
    }
    return false;
}

}  // namespace

std::string sourceCaption(const char* source, bool have_state) {
    if (const Src* s = find(source)) return s->caption;
    if (!empty(source)) return upper(source);
    return have_state ? "BOOMBOX" : "";
}

FaceText faceText(const FaceInput& in) {
    FaceText f;
    const bool has_title = !empty(in.title);
    const bool has_text = has_title || !empty(in.artist);
    const bool active = !empty(in.source);

    if (in.home) {
        f.headline = "Home";
        f.sub = "Choose a source";
        if (in.playing && active) {
            f.note = "Playing: ";
            f.note += has_text ? (has_title ? in.title : in.artist)
                               : friendlyName(in.source);
            f.transport = true;
        }
        return f;
    }

    f.label = sourceCaption(in.source, in.have_state);
    if (has_text) {
        f.headline = has_title ? in.title : in.artist;
        f.sub = has_title ? std::string(in.artist ? in.artist : "") : std::string();
        // A movie's series/episode text: "Show - S01E02 - Name".
        if (has_title && empty(in.artist) && !empty(in.source) &&
            std::strcmp(in.source, "movies") == 0) {
            const std::string t(in.title);
            const size_t cut = t.find(" - ");
            if (cut != std::string::npos && cut > 0 && hasEpisodeMarker(t)) {
                f.headline = t.substr(0, cut);
                f.sub = t.substr(cut + 3);
            }
        }
        f.transport = true;
        f.progress = true;
        return f;
    }
    if (active) {
        f.headline = friendlyName(in.source);
        f.sub = in.playing ? "Playing" : "Paused";
        f.transport = true;
        return f;
    }
    f.headline = "Nothing playing";
    return f;
}

}  // namespace knob
