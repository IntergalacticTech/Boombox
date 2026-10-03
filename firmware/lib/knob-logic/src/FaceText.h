// What the knob's face says, from the consolidated state. Pure C++ (no
// Arduino/LVGL), unit-tested natively.
//
//   * Home view (kiosk on its input picker): "Home" / "Choose a source", and
//     only if something is actually playing a small "Playing: <title>" —
//     never a stale track as the main text.
//   * A track: the source caption (LIBRARY, AIRPLAY, SPOTIFY, BLUETOOTH,
//     VIDEO), the title and the artist. A movie whose title carries series/
//     episode text ("Show - S01E02 - Name") is split over the two lines.
//   * An active source with no metadata (a Bluetooth phone without AVRCP):
//     the source's name and "Playing"/"Paused".
//   * Nothing: "Nothing playing".
//
// Text is expected already folded to what the font can draw.
#pragma once
#include <string>

namespace knob {

struct FaceInput {
    const char* source = "";   // state.source ("mopidy", "movies", … or "")
    bool home = false;         // state.view == "home"
    bool playing = false;
    const char* title = "";
    const char* artist = "";
    bool have_state = true;    // any state received yet
};

struct FaceText {
    std::string label;         // small accent caption above the title
    std::string headline;      // big centre line
    std::string sub;           // second line ("" = hidden)
    std::string note;          // small extra line ("" = hidden)
    bool transport = false;    // show the play/pause glyph
    bool progress = false;     // show the progress ring (when a duration is known)
};

// Caption for a source id: "movies" → "VIDEO", "mopidy" → "LIBRARY", …,
// unknown ids upper-cased, "" → "BOOMBOX" (or "" before any state).
std::string sourceCaption(const char* source, bool have_state = true);

FaceText faceText(const FaceInput& in);

}  // namespace knob
