// Shared: track data, transport icons, fake reactive levels
// All globals exported via window.* so other Babel scripts can read them.

const TRACKS = [
  { artist: "Khruangbin",       title: "Maria También",         album: "Con Todo El Mundo", time: "3:48", len: 228, hue: 18  },
  { artist: "Boards of Canada", title: "Roygbiv",               album: "Music Has the Right to Children", time: "2:31", len: 151, hue: 200 },
  { artist: "Aphex Twin",       title: "Avril 14th",            album: "Drukqs",            time: "2:05", len: 125, hue: 150 },
  { artist: "Tame Impala",      title: "Let It Happen",         album: "Currents",          time: "7:47", len: 467, hue: 280 },
  { artist: "Burial",           title: "Archangel",             album: "Untrue",            time: "3:53", len: 233, hue: 240 },
  { artist: "Sade",             title: "Cherish the Day",       album: "Love Deluxe",       time: "5:31", len: 331, hue: 32  },
  { artist: "Charli XCX",       title: "Von dutch",             album: "BRAT",              time: "2:42", len: 162, hue: 80  },
  { artist: "Massive Attack",   title: "Teardrop",              album: "Mezzanine",         time: "5:31", len: 331, hue: 350 },
];

const SOURCES = [
  { id:"local",     label:"LOCAL",      sub:"Pi · 2,481 tracks",   icon:"hd" },
  { id:"bluetooth", label:"BLUETOOTH",  sub:"Phone · paired",      icon:"bt" },
  { id:"cast",      label:"CAST",       sub:"Living Room TV",      icon:"cast" },
  { id:"airplay",   label:"AIRPLAY",    sub:"Boombox · receiver",  icon:"airplay" },
  { id:"spotify",   label:"SPOTIFY",    sub:"jwc · connected",     icon:"spot" },
  { id:"radio",     label:"RADIO",      sub:"WFMU · 91.1",         icon:"radio" },
];

// Inline SVG icon set, drawn as primitives (lines/circles/rects only).
function Icon({ name, size = 24, stroke = "currentColor", sw = 2 }) {
  const p = { width:size, height:size, viewBox:"0 0 24 24", fill:"none", stroke, strokeWidth:sw, strokeLinecap:"round", strokeLinejoin:"round" };
  switch (name) {
    case "play":    return <svg {...p}><path d="M6 4 L20 12 L6 20 Z" fill={stroke}/></svg>;
    case "pause":   return <svg {...p}><rect x="6" y="4" width="4" height="16" fill={stroke}/><rect x="14" y="4" width="4" height="16" fill={stroke}/></svg>;
    case "next":    return <svg {...p}><path d="M5 4 L15 12 L5 20 Z" fill={stroke}/><line x1="18" y1="4" x2="18" y2="20"/></svg>;
    case "prev":    return <svg {...p}><path d="M19 4 L9 12 L19 20 Z" fill={stroke}/><line x1="6" y1="4" x2="6" y2="20"/></svg>;
    case "shuffle": return <svg {...p}><path d="M3 7 L7 7 L17 17 L21 17"/><path d="M21 17 L18 14 M21 17 L18 20"/><path d="M3 17 L7 17 L11 13"/><path d="M14 10 L17 7 L21 7"/><path d="M21 7 L18 4 M21 7 L18 10"/></svg>;
    case "repeat":  return <svg {...p}><path d="M4 9 V7 a2 2 0 0 1 2-2 H18 a2 2 0 0 1 2 2 V11"/><path d="M20 11 L17 8 M20 11 L17 14"/><path d="M20 15 V17 a2 2 0 0 1-2 2 H6 a2 2 0 0 1-2-2 V13"/><path d="M4 13 L7 16 M4 13 L7 10"/></svg>;
    case "vol":     return <svg {...p}><path d="M3 9 H7 L12 5 V19 L7 15 H3 Z" fill={stroke}/><path d="M16 8 a5 5 0 0 1 0 8" fill="none"/><path d="M19 5 a9 9 0 0 1 0 14" fill="none"/></svg>;
    case "search":  return <svg {...p}><circle cx="11" cy="11" r="6"/><line x1="20" y1="20" x2="16" y2="16"/></svg>;
    case "queue":   return <svg {...p}><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="14" y2="18"/></svg>;
    case "hd":      return <svg {...p}><rect x="3" y="6" width="18" height="12" rx="1"/><circle cx="8" cy="12" r="1.5" fill={stroke}/><line x1="13" y1="12" x2="18" y2="12"/></svg>;
    case "bt":      return <svg {...p}><path d="M8 5 L16 12 L12 15 L12 5 L16 12 L12 15 L12 22 L16 17 L8 12"/></svg>;
    case "cast":    return <svg {...p}><path d="M3 17 a2 2 0 0 1 2 2"/><path d="M3 13 a6 6 0 0 1 6 6"/><path d="M3 9 a10 10 0 0 1 10 10"/><rect x="3" y="4" width="18" height="14" rx="1" fill="none"/></svg>;
    case "airplay": return <svg {...p}><path d="M5 17 H4 a1 1 0 0 1 -1 -1 V5 a1 1 0 0 1 1 -1 H20 a1 1 0 0 1 1 1 V16 a1 1 0 0 1 -1 1 H19"/><path d="M8 21 L12 16 L16 21 Z" fill={stroke}/></svg>;
    case "spot":    return <svg {...p}><circle cx="12" cy="12" r="9"/><path d="M7 9 c4 -1 9 0 11 2"/><path d="M7.5 13 c3.5 -1 7.5 0 9.5 1.5"/><path d="M8 16.5 c3 -1 6 0 7.5 1"/></svg>;
    case "radio":   return <svg {...p}><path d="M5 10 L19 5"/><rect x="3" y="9" width="18" height="11" rx="1"/><circle cx="16" cy="14.5" r="2.5"/><line x1="6" y1="13" x2="11" y2="13"/><line x1="6" y1="17" x2="9" y2="17"/></svg>;
    case "power":   return <svg {...p}><path d="M12 4 V11"/><path d="M7 7 a7 7 0 1 0 10 0"/></svg>;
    case "settings":return <svg {...p}><circle cx="12" cy="12" r="3"/><path d="M12 2 V5 M12 19 V22 M2 12 H5 M19 12 H22 M5 5 L7 7 M17 17 L19 19 M5 19 L7 17 M17 7 L19 5"/></svg>;
    case "eq":      return <svg {...p}><line x1="6" y1="4" x2="6" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/><line x1="18" y1="4" x2="18" y2="20"/><circle cx="6" cy="9" r="2" fill={stroke}/><circle cx="12" cy="14" r="2" fill={stroke}/><circle cx="18" cy="11" r="2" fill={stroke}/></svg>;
    case "wifi":    return <svg {...p}><path d="M3 9 a14 14 0 0 1 18 0"/><path d="M6 13 a10 10 0 0 1 12 0"/><path d="M9 17 a6 6 0 0 1 6 0"/><circle cx="12" cy="20" r="0.8" fill={stroke}/></svg>;
    case "x":       return <svg {...p}><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>;
    case "check":   return <svg {...p}><path d="M5 12 L10 17 L20 7"/></svg>;
    case "chevron": return <svg {...p}><path d="M9 6 L15 12 L9 18"/></svg>;
    case "dot":     return <svg {...p}><circle cx="12" cy="12" r="3" fill={stroke}/></svg>;
    case "back":    return <svg {...p}><path d="M15 6 L9 12 L15 18"/></svg>;
    case "fwd10":   return <svg {...p}><path d="M19 8 a8 8 0 1 0 1.5 4"/><path d="M19 4 V8 H15"/><text x="12" y="15" textAnchor="middle" fontSize="7" fill={stroke} stroke="none" fontFamily="monospace" fontWeight="700">10</text></svg>;
    case "back10":  return <svg {...p}><path d="M5 8 a8 8 0 1 1 -1.5 4"/><path d="M5 4 V8 H9"/><text x="12" y="15" textAnchor="middle" fontSize="7" fill={stroke} stroke="none" fontFamily="monospace" fontWeight="700">10</text></svg>;
    default:        return <svg {...p}><circle cx="12" cy="12" r="8"/></svg>;
  }
}

// useTicker: returns an integer that increments at ~30fps for ambient anims.
// Components convert it into pseudo-random VU values via a stable seed.
function useTicker(intervalMs = 80) {
  const [t, setT] = React.useState(0);
  React.useEffect(() => {
    let id;
    const tick = () => { setT(x => x + 1); id = setTimeout(tick, intervalMs); };
    id = setTimeout(tick, intervalMs);
    return () => clearTimeout(id);
  }, [intervalMs]);
  return t;
}

// Deterministic-ish noise — wobbly VU values that look organic but loop.
function vu(t, seed = 0) {
  const a = Math.sin((t * 0.13) + seed * 1.7) * 0.5 + 0.5;
  const b = Math.sin((t * 0.31) + seed * 0.9 + 1.1) * 0.5 + 0.5;
  const c = Math.sin((t * 0.07) + seed * 2.3 + 0.4) * 0.5 + 0.5;
  return Math.min(1, Math.max(0, a * 0.55 + b * 0.30 + c * 0.20));
}

// Format seconds → m:ss
function mmss(s) {
  s = Math.max(0, Math.floor(s));
  return `${Math.floor(s/60)}:${String(s%60).padStart(2,"0")}`;
}

Object.assign(window, { TRACKS, SOURCES, Icon, useTicker, vu, mmss });
