// Self-hosted fonts so the boombox doesn't need internet at boot for typography.
// fontsource ships woff2 files bundled by Vite into the dist/ output.
//
// Latin subset only: the bare `<weight>.css` entry points pull in every
// subset (cyrillic, greek, vietnamese, latin-ext…) — ~1.9 MB of font files
// the UI never renders. The latin files carry no unicode-range, so any
// out-of-subset glyph just falls back to the next family in the stack.

import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";
import "@fontsource/inter/latin-800.css";

import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import "@fontsource/jetbrains-mono/latin-600.css";
import "@fontsource/jetbrains-mono/latin-700.css";

import "@fontsource/space-grotesk/latin-400.css";
import "@fontsource/space-grotesk/latin-500.css";
import "@fontsource/space-grotesk/latin-700.css";

import "@fontsource/archivo-black/latin-400.css";
