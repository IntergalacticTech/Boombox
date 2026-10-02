#include "TextFold.h"

#include <stdint.h>

namespace knob {

namespace {

// U+00C0..U+00FF → ASCII.
const char* const LATIN1[64] = {
    "A", "A", "A", "A", "A", "A", "AE", "C",    // C0-C7
    "E", "E", "E", "E", "I", "I", "I", "I",     // C8-CF
    "D", "N", "O", "O", "O", "O", "O", "x",     // D0-D7
    "O", "U", "U", "U", "U", "Y", "Th", "ss",   // D8-DF
    "a", "a", "a", "a", "a", "a", "ae", "c",    // E0-E7
    "e", "e", "e", "e", "i", "i", "i", "i",     // E8-EF
    "d", "n", "o", "o", "o", "o", "o", "/",     // F0-F7
    "o", "u", "u", "u", "u", "y", "th", "y",    // F8-FF
};

const char* foldCodepoint(uint32_t cp) {
    if (cp >= 0xC0 && cp <= 0xFF) return LATIN1[cp - 0xC0];
    switch (cp) {
        case 0xA0: return " ";
        case 0xA1: return "!";
        case 0xBF: return "?";
        case 0xB4: case 0x2018: case 0x2019: case 0x201A: case 0x2032: return "'";
        case 0x201C: case 0x201D: case 0x201E: case 0x2033: return "\"";
        case 0x2010: case 0x2011: case 0x2012: case 0x2013: case 0x2014:
        case 0x2015: case 0x2212: return "-";
        case 0x2026: return "...";
        case 0x2022: case 0xB7: return "*";
        case 0x152: return "OE";
        case 0x153: return "oe";
        case 0x160: return "S";
        case 0x161: return "s";
        case 0x17D: return "Z";
        case 0x17E: return "z";
        case 0x178: return "Y";
        default: return "?";
    }
}

}  // namespace

std::string foldToAscii(const char* s) {
    std::string out;
    if (!s) return out;
    const unsigned char* p = reinterpret_cast<const unsigned char*>(s);
    while (*p) {
        const unsigned char c = *p;
        if (c < 0x80) {
            out += (c >= 0x20 || c == '\n') ? (char)c : ' ';
            p++;
            continue;
        }
        int extra = (c & 0xE0) == 0xC0 ? 1 : (c & 0xF0) == 0xE0 ? 2 : (c & 0xF8) == 0xF0 ? 3 : -1;
        if (extra < 0) { out += '?'; p++; continue; }
        uint32_t cp = c & (0x3F >> extra);
        int i = 1;
        for (; i <= extra; i++) {
            if ((p[i] & 0xC0) != 0x80) break;
            cp = (cp << 6) | (p[i] & 0x3F);
        }
        if (i <= extra) { out += '?'; p += i; continue; }   // truncated sequence
        out += foldCodepoint(cp);
        p += extra + 1;
    }
    return out;
}

}  // namespace knob
