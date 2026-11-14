// Folds UTF-8 text to what LVGL's built-in Montserrat fonts can draw
// (printable ASCII). Latin-1 letters lose their accents (é → e, ß → ss),
// typographic punctuation becomes its ASCII cousin (’ → ', — → -, … → ...),
// anything else becomes '?'. Pure C++, unit-tested natively.
#pragma once
#include <string>

namespace knob {

std::string foldToAscii(const char* utf8);

}  // namespace knob
