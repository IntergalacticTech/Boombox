#include "HostLink.h"

namespace knob {

bool LineAssembler::feed(char c) {
    if (_ready) {   // the previous line has been consumed
        _ready = false;
        _len = 0;
        _buf[0] = 0;
    }
    if (c == '\n' || c == '\r') {
        if (_overflow) {
            _overflow = false;
            _len = 0;
            _buf[0] = 0;
            return false;
        }
        if (_len == 0) return false;
        _buf[_len] = 0;
        _ready = true;
        return true;
    }
    if (_overflow) return false;
    if (_len >= CAP) {
        _overflow = true;
        _dropped++;
        _len = 0;
        _buf[0] = 0;
        return false;
    }
    _buf[_len++] = c;
    return false;
}

bool isProtocolLine(const char* s) {
    if (!s) return false;
    while (*s == ' ' || *s == '\t') s++;
    return *s == '{';
}

bool isJsonNumber(const char* s) {
    if (!s) return false;
    const char* p = s;
    if (*p == '-') p++;
    if (*p == '0') {
        p++;
    } else if (*p >= '1' && *p <= '9') {
        while (*p >= '0' && *p <= '9') p++;
    } else {
        return false;
    }
    if (*p == '.') {
        p++;
        if (!(*p >= '0' && *p <= '9')) return false;
        while (*p >= '0' && *p <= '9') p++;
    }
    if (*p == 'e' || *p == 'E') {
        p++;
        if (*p == '+' || *p == '-') p++;
        if (!(*p >= '0' && *p <= '9')) return false;
        while (*p >= '0' && *p <= '9') p++;
    }
    return *p == 0;
}

}  // namespace knob
