#include "DebugConsole.h"

#include <lvgl.h>
#include <vector>

namespace knob {

namespace {
struct Cmd {
    String name;
    String help;
    ConsoleHandler fn;
};
std::vector<Cmd> g_cmds;
String g_line;
constexpr size_t MAX_LINE = 2048;

const char B64[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

// Encodes `n` bytes (n % 3 == 0 except for the final chunk) into `out`.
size_t b64(const uint8_t* in, size_t n, char* out) {
    size_t o = 0;
    size_t i = 0;
    for (; i + 2 < n; i += 3) {
        const uint32_t v = (in[i] << 16) | (in[i + 1] << 8) | in[i + 2];
        out[o++] = B64[(v >> 18) & 63];
        out[o++] = B64[(v >> 12) & 63];
        out[o++] = B64[(v >> 6) & 63];
        out[o++] = B64[v & 63];
    }
    if (i < n) {
        uint32_t v = in[i] << 16;
        if (i + 1 < n) v |= in[i + 1] << 8;
        out[o++] = B64[(v >> 18) & 63];
        out[o++] = B64[(v >> 12) & 63];
        out[o++] = (i + 1 < n) ? B64[(v >> 6) & 63] : '=';
        out[o++] = '=';
    }
    out[o] = 0;
    return o;
}

void dispatch(String line) {
    line.trim();
    if (!line.length()) return;
    int sp = line.indexOf(' ');
    String name = sp < 0 ? line : line.substring(0, sp);
    String args = sp < 0 ? String() : line.substring(sp + 1);
    args.trim();
    if (name == "help") {
        Serial.println("[console] commands:");
        for (auto& c : g_cmds)
            Serial.printf("  %-8s %s\n", c.name.c_str(), c.help.c_str());
        return;
    }
    for (auto& c : g_cmds) {
        if (c.name == name) {
            c.fn(args);
            return;
        }
    }
    Serial.printf("[console] unknown command '%s' (try help)\n", name.c_str());
}
}  // namespace

void consoleBegin() {
    g_line.reserve(MAX_LINE);
    consoleOn("snap", "stream an LVGL snapshot (RGB565, base64)",
              [](const String&) { consoleSnapshot(); });
}

void consoleOn(const char* name, const char* help, ConsoleHandler handler) {
    g_cmds.push_back(Cmd{String(name), String(help), std::move(handler)});
}

void consolePoll() {
    // Bounded per call so a flood of input can't starve LVGL.
    int budget = 512;
    while (Serial.available() > 0 && budget-- > 0) {
        const int c = Serial.read();
        if (c < 0) break;
        if (c == '\n' || c == '\r') {
            if (g_line.length()) {
                String line = g_line;
                g_line = "";
                dispatch(line);
            }
        } else if (g_line.length() < MAX_LINE) {
            g_line += (char)c;
        }
    }
}

void consoleSnapshot() {
    lv_obj_t* scr = lv_screen_active();
    lv_obj_update_layout(scr);
    const uint32_t t0 = millis();
    lv_draw_buf_t* db = lv_snapshot_take(scr, LV_COLOR_FORMAT_RGB565);
    if (!db) {
        Serial.println("SNAPERR snapshot allocation failed");
        return;
    }
    // The snapshot is ~600 KB of base64; give a briefly busy host more slack
    // than the default 100 ms before USB-Serial/JTAG starts dropping bytes.
    Serial.setTxTimeoutMs(1500);
    const uint32_t w = db->header.w;
    const uint32_t h = db->header.h;
    const uint32_t stride = db->header.stride;
    const uint32_t row_bytes = w * 2;
    Serial.printf("SNAP %u %u %u RGB565\n", (unsigned)w, (unsigned)h,
                  (unsigned)(row_bytes * h));
    // One base64 line per 768 raw bytes (1024 chars); rows are packed
    // (stride padding dropped) so the host sees exactly w*h*2 bytes.
    static uint8_t chunk[768];
    static char line[1024 + 8];
    size_t fill = 0;
    for (uint32_t y = 0; y < h; y++) {
        const uint8_t* row = db->data + y * stride;
        uint32_t off = 0;
        while (off < row_bytes) {
            const uint32_t take = min<uint32_t>(row_bytes - off, sizeof(chunk) - fill);
            memcpy(chunk + fill, row + off, take);
            fill += take;
            off += take;
            if (fill == sizeof(chunk)) {
                b64(chunk, fill, line);
                Serial.println(line);
                fill = 0;
            }
        }
    }
    if (fill) {
        b64(chunk, fill, line);
        Serial.println(line);
    }
    Serial.println("SNAPEND");
    Serial.flush();
    Serial.setTxTimeoutMs(100);
    Serial.printf("[snap] %ux%u in %u ms\n", (unsigned)w, (unsigned)h,
                  (unsigned)(millis() - t0));
    lv_draw_buf_destroy(db);
}

}  // namespace knob
