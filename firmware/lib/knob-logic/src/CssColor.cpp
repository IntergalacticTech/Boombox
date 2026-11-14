#include "CssColor.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

namespace knob {

namespace {

int hexVal(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool parseHex(const char* s, size_t n, Rgba& out) {
    int v[8];
    for (size_t i = 0; i < n; i++) {
        v[i] = hexVal(s[i]);
        if (v[i] < 0) return false;
    }
    Rgba c;
    if (n == 3 || n == 4) {
        c.r = (uint8_t)(v[0] * 17);
        c.g = (uint8_t)(v[1] * 17);
        c.b = (uint8_t)(v[2] * 17);
        c.a = n == 4 ? (uint8_t)(v[3] * 17) : 255;
    } else if (n == 6 || n == 8) {
        c.r = (uint8_t)(v[0] * 16 + v[1]);
        c.g = (uint8_t)(v[2] * 16 + v[3]);
        c.b = (uint8_t)(v[4] * 16 + v[5]);
        c.a = n == 8 ? (uint8_t)(v[6] * 16 + v[7]) : 255;
    } else {
        return false;
    }
    out = c;
    return true;
}

const char* skipWs(const char* p) {
    while (*p && isspace((unsigned char)*p)) p++;
    return p;
}

int clampByte(double v) {
    if (v < 0) return 0;
    if (v > 255) return 255;
    return (int)(v + 0.5);
}

// Parses one numeric component; `pct` reports a trailing '%'.
bool parseNum(const char*& p, double& v, bool& pct) {
    p = skipWs(p);
    char* end = nullptr;
    v = strtod(p, &end);
    if (end == p) return false;
    p = skipWs(end);
    pct = false;
    if (*p == '%') {
        pct = true;
        p = skipWs(p + 1);
    }
    return true;
}

bool ieq(const char* a, size_t n, const char* b) {
    if (strlen(b) != n) return false;
    for (size_t i = 0; i < n; i++)
        if (tolower((unsigned char)a[i]) != b[i]) return false;
    return true;
}

}  // namespace

bool parseCssColor(const char* s, Rgba& out) {
    if (!s) return false;
    const char* p = skipWs(s);
    size_t n = strlen(p);
    while (n && isspace((unsigned char)p[n - 1])) n--;
    if (!n) return false;

    if (p[0] == '#') return parseHex(p + 1, n - 1, out);

    struct Named { const char* name; Rgba c; };
    static const Named NAMED[] = {
        {"black", {0, 0, 0, 255}},       {"white", {255, 255, 255, 255}},
        {"transparent", {0, 0, 0, 0}},   {"red", {255, 0, 0, 255}},
        {"green", {0, 128, 0, 255}},     {"blue", {0, 0, 255, 255}},
        {"gray", {128, 128, 128, 255}},  {"grey", {128, 128, 128, 255}},
    };
    for (const auto& nm : NAMED) {
        if (ieq(p, n, nm.name)) {
            out = nm.c;
            return true;
        }
    }

    // rgb( / rgba(
    size_t fn = 0;
    while (fn < n && isalpha((unsigned char)p[fn])) fn++;
    if (!(ieq(p, fn, "rgb") || ieq(p, fn, "rgba"))) return false;
    const char* q = skipWs(p + fn);
    if (*q != '(') return false;
    q++;

    double comp[4] = {0, 0, 0, 1};
    int count = 0;
    for (; count < 4; count++) {
        double v;
        bool pct;
        if (!parseNum(q, v, pct)) break;
        if (count < 3) comp[count] = pct ? v * 255.0 / 100.0 : v;
        else           comp[count] = pct ? v / 100.0 : v;
        // Separators: comma, whitespace (CSS4), or '/' before alpha.
        if (*q == ',' || *q == '/') q++;
    }
    q = skipWs(q);
    if (*q != ')' || count < 3) return false;

    Rgba c;
    c.r = (uint8_t)clampByte(comp[0]);
    c.g = (uint8_t)clampByte(comp[1]);
    c.b = (uint8_t)clampByte(comp[2]);
    double a = comp[3];
    if (a < 0) a = 0;
    if (a > 1) a = 1;
    c.a = (uint8_t)clampByte(a * 255.0);
    out = c;
    return true;
}

Rgba blendOver(const Rgba& fg, const Rgba& bg) {
    Rgba o;
    const uint32_t a = fg.a;
    o.r = (uint8_t)((fg.r * a + bg.r * (255 - a) + 127) / 255);
    o.g = (uint8_t)((fg.g * a + bg.g * (255 - a) + 127) / 255);
    o.b = (uint8_t)((fg.b * a + bg.b * (255 - a) + 127) / 255);
    o.a = 255;
    return o;
}

Rgba mix(const Rgba& x, const Rgba& y, uint8_t t) {
    Rgba o;
    o.r = (uint8_t)((x.r * (255 - t) + y.r * t + 127) / 255);
    o.g = (uint8_t)((x.g * (255 - t) + y.g * t + 127) / 255);
    o.b = (uint8_t)((x.b * (255 - t) + y.b * t + 127) / 255);
    o.a = 255;
    return o;
}

uint8_t luma(const Rgba& c) {
    return (uint8_t)((c.r * 54 + c.g * 183 + c.b * 19) >> 8);
}

}  // namespace knob
