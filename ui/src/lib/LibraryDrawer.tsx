// LibraryDrawer — tappable browser for Mopidy library so the user can pick
// songs from the touchscreen instead of always reaching for a phone.
//
// Two-pane navigation: the user moves through directory refs (Albums / Artists
// / Tracks → album content → tracks). Tapping a track plays it and queues the
// album behind it; tapping "Play all" plays the whole album.
//
// We don't try to render cover art here — Mopidy's get_images returns paths
// that need a separate proxy to be reachable from the browser. Track lists
// alone are already a huge UX win over "use your phone".

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { browse, getHistory, lookup, playUris, queueUris, search, ROOTS, RADIO_STATIONS, type Ref, type MopidyTrack, type HistoryEntry, type RadioStation } from "./library";
import { AlbumThumb } from "./AlbumThumb";
import { getFavorites } from "./favorites";

type Crumb = { uri: string | null; name: string };

function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function joinArtists(track: MopidyTrack): string {
  return (track.artists ?? []).map(a => a?.name).filter(Boolean).join(", ");
}

function relativeTime(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 0) return "now";
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

type Props = { onClose: () => void };

export function LibraryDrawer({ onClose }: Props) {
  // Stack of breadcrumbs we've drilled into. Empty = at the top-level menu.
  const [stack, setStack] = useState<Crumb[]>([]);
  const [items, setItems] = useState<Ref[]>(ROOTS);
  const [tracks, setTracks] = useState<MopidyTrack[] | null>(null);
  const [history, setHistory] = useState<HistoryEntry[] | null>(null);
  const [radio, setRadio] = useState<RadioStation[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MopidyTrack[] | null>(null);
  const [searching, setSearching] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);

  const here = stack.length === 0 ? null : stack[stack.length - 1];
  const hereUri = here?.uri ?? null;
  const searchActive = query.trim().length > 0;

  // Debounced search. When the query is non-empty, we override the directory
  // browse with a flat track list of search results.
  useEffect(() => {
    const q = query.trim();
    if (!q) { setSearchResults(null); setSearching(false); return; }
    setSearching(true);
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const hits = await search(q);
        if (!cancelled) setSearchResults(hits);
      } catch {
        if (!cancelled) setSearchResults([]);
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 220);
    return () => { cancelled = true; clearTimeout(t); };
  }, [query]);

  // Whenever we descend, fetch directory contents OR resolve track metadata.
  useEffect(() => {
    if (searchActive) return; // search has its own loader
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        if (!hereUri) {
          setItems(ROOTS);
          setTracks(null);
          setHistory(null);
          setRadio(null);
        } else if (hereUri === "boombox:favorites") {
          // Resolve favourite track URIs to full metadata for thumbs/labels.
          const uris = getFavorites();
          setItems([]);
          setHistory(null);
          setRadio(null);
          if (uris.length === 0) {
            setTracks([]);
          } else {
            try {
              const lk = await lookup(uris);
              if (cancelled) return;
              const flat = uris.flatMap(u => lk[u] ?? []);
              setTracks(flat);
            } catch {
              setTracks([]);
            }
          }
        } else if (hereUri === "boombox:radio") {
          setRadio(RADIO_STATIONS);
          setItems([]);
          setTracks(null);
          setHistory(null);
        } else if (hereUri === "boombox:recent") {
          // Special: fetch Mopidy's playback history. We resolve full metadata
          // for each unique URI so rows show artist + album for art lookup.
          const hist = await getHistory();
          if (cancelled) return;
          setHistory(hist);
          setItems([]);
          setTracks(null);
          // Best-effort metadata for art / artist labels.
          const uniq = Array.from(new Set(hist.map(h => h.ref.uri)));
          if (uniq.length > 0) {
            try {
              const lk = await lookup(uniq);
              if (!cancelled) {
                // Rebuild ordered list with resolved tracks where available.
                const resolved = hist
                  .map(h => (lk[h.ref.uri] ?? [])[0])
                  .filter(Boolean);
                if (resolved.length > 0) setTracks(resolved);
              }
            } catch {
              // fall through; we'll render from ref.name only
            }
          }
        } else {
          const refs = await browse(hereUri);
          if (cancelled) return;
          setItems(refs);
          setHistory(null);
          setRadio(null);
          // If the directory is mostly tracks, resolve their metadata so we can
          // show duration / artist beside the file name.
          const trackUris = refs.filter(r => r.type === "track").map(r => r.uri);
          if (trackUris.length > 0 && trackUris.length === refs.length) {
            // Pure track list — resolve metadata.
            try {
              const lk = await lookup(trackUris);
              if (cancelled) return;
              const flat = trackUris.flatMap(u => lk[u] ?? []);
              setTracks(flat);
            } catch {
              setTracks(null);
            }
          } else {
            setTracks(null);
          }
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    if (listRef.current) listRef.current.scrollTop = 0;
    return () => { cancelled = true; };
  }, [hereUri, searchActive]);

  // Esc closes; backspace navigates up.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (stack.length > 0) setStack(s => s.slice(0, -1));
        else onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [stack, onClose]);

  const allTrackUris = useMemo(() => {
    if (searchActive && searchResults) return searchResults.map(t => t.uri);
    if (history) return history.map(h => h.ref.uri);
    if (tracks) return tracks.map(t => t.uri);
    return items.filter(r => r.type === "track").map(r => r.uri);
  }, [items, tracks, searchActive, searchResults, history]);

  const visibleTracks = searchActive ? (searchResults ?? []) : tracks;

  const playAll = async () => {
    if (allTrackUris.length === 0) return;
    await playUris(allTrackUris);
    onClose();
  };

  const playTrackAt = async (idx: number) => {
    if (allTrackUris.length === 0) return;
    const head = allTrackUris[idx];
    const tail = allTrackUris.slice(idx + 1);
    await playUris([head]);
    if (tail.length > 0) await queueUris(tail);
    onClose();
  };

  const enterRef = (r: Ref) => {
    if (r.type === "track") {
      // Play this track immediately + queue the rest of the visible track list.
      const idx = items.findIndex(i => i.uri === r.uri);
      void playTrackAt(idx === -1 ? 0 : idx);
      return;
    }
    setStack(s => [...s, { uri: r.uri, name: r.name }]);
  };

  /** Play every track inside a directory (album/artist) without drilling in. */
  const playRefImmediate = async (r: Ref) => {
    try {
      const refs = await browse(r.uri);
      const trackUris = refs.filter(x => x.type === "track").map(x => x.uri);
      if (trackUris.length === 0) return;
      await playUris(trackUris);
      onClose();
    } catch { /* ignore */ }
  };

  return (
    <div
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.92)",
        backdropFilter: "blur(20px)",
        zIndex: 9990,
        display: "flex",
        alignItems: "stretch",
        justifyContent: "center",
        padding: 16,
        fontFamily: "Inter, system-ui, sans-serif",
        color: "#fff",
      }}
    >
      <div style={{
        width: "min(1100px, 96vw)",
        maxHeight: "100%",
        background: "#0a0a0a",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 16,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{
          padding: "14px 18px",
          borderBottom: "1px solid rgba(255,255,255,0.10)",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}>
          <div style={{display: "flex", alignItems: "center", gap: 12, minHeight: 44}}>
            <button
              onClick={() => stack.length > 0 ? setStack(s => s.slice(0, -1)) : onClose()}
              style={{
                padding: "10px 14px",
                background: "rgba(255,255,255,0.08)",
                border: "1px solid rgba(255,255,255,0.15)",
                borderRadius: 999,
                color: "#fff", fontSize: 14, cursor: "pointer",
                minWidth: 64,
              }}
            >{stack.length > 0 ? "‹ Back" : "Close"}</button>

            <div style={{flex: 1, minWidth: 0}}>
              <div style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11, letterSpacing: "0.18em",
                color: "rgba(255,255,255,0.55)",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>
                {searchActive
                  ? `SEARCH${searching ? " · …" : ""}`
                  : `LIBRARY${stack.length > 0 ? " › " + stack.map(c => c.name).join(" › ") : ""}`}
              </div>
              <div style={{
                fontSize: 18, fontWeight: 700, marginTop: 2,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>
                {searchActive ? `“${query}”` : (here ? here.name : "Browse")}
              </div>
            </div>

            {allTrackUris.length > 0 && (
              <button
                onClick={playAll}
                style={{
                  padding: "10px 18px",
                  background: "#5be7ff",
                  color: "#000",
                  border: "none",
                  borderRadius: 999,
                  fontWeight: 700, fontSize: 13,
                  letterSpacing: "0.06em",
                  cursor: "pointer",
                }}
              >▶ PLAY ALL ({allTrackUris.length})</button>
            )}
          </div>

          {/* Search input — always visible. Empty query = browse mode. */}
          <div style={{position: "relative"}}>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search library…"
              style={{
                width: "100%",
                padding: "12px 16px 12px 40px",
                background: "rgba(255,255,255,0.06)",
                border: "1px solid rgba(255,255,255,0.12)",
                borderRadius: 10,
                color: "#fff",
                fontSize: 15,
                fontFamily: "Inter, system-ui, sans-serif",
                outline: "none",
              }}
            />
            <span style={{
              position: "absolute",
              left: 14, top: "50%", transform: "translateY(-50%)",
              color: "rgba(255,255,255,0.5)",
              fontSize: 16, pointerEvents: "none",
            }}>⌕</span>
            {query && (
              <button
                onClick={() => setQuery("")}
                style={{
                  position: "absolute",
                  right: 8, top: "50%", transform: "translateY(-50%)",
                  width: 28, height: 28,
                  background: "rgba(255,255,255,0.10)",
                  border: "none",
                  borderRadius: 999,
                  color: "#fff", cursor: "pointer",
                  fontSize: 14,
                }}
              >×</button>
            )}
          </div>
        </div>

        {/* Body */}
        <div ref={listRef} style={{
          flex: 1,
          overflowY: "auto",
          overflowX: "hidden",
          // Scroll snapping isn't ideal for music lists; just plain scroll.
        }}>
          {error && (
            <div style={{padding: 24, color: "#ff8b8b"}}>Library error: {error}</div>
          )}
          {loading && !error && (
            <div style={{padding: 24, fontFamily: "'JetBrains Mono', monospace", color: "rgba(255,255,255,0.6)"}}>Loading…</div>
          )}
          {!loading && !error && (
            <div>
              {radio && !searchActive
                ? (
                    <div style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
                      gap: 12,
                      padding: 12,
                    }}>
                      {radio.map(st => (
                        <button
                          key={st.id}
                          onClick={() => { void playUris([st.stream]).then(onClose); }}
                          style={{
                            background: "rgba(255,255,255,0.04)",
                            border: "1px solid rgba(255,255,255,0.10)",
                            borderRadius: 12,
                            padding: 12,
                            cursor: "pointer",
                            color: "inherit",
                            display: "flex",
                            flexDirection: "column",
                            gap: 8,
                            minHeight: 130,
                            textAlign: "left",
                          }}
                        >
                          <div style={{
                            width: 56, height: 56, borderRadius: 12,
                            background: `linear-gradient(135deg, ${st.accent}, rgba(0,0,0,0.4))`,
                            display: "grid", placeItems: "center",
                            color: "#000", fontSize: 22, fontWeight: 800,
                          }}>📻</div>
                          <div style={{
                            fontSize: 14, fontWeight: 700, letterSpacing: "-0.01em",
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                          }}>{st.name}</div>
                          <div style={{
                            fontSize: 11,
                            color: "rgba(255,255,255,0.55)",
                            fontFamily: "'JetBrains Mono', monospace",
                            letterSpacing: "0.04em",
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                          }}>{st.blurb}</div>
                        </button>
                      ))}
                    </div>
                  )
                : history && !searchActive
                ? history.map((h, i) => {
                    // Lookup resolved metadata if we got it, else fall back to
                    // the Ref's "Artist - Title" name.
                    const t = (tracks ?? []).find(x => x.uri === h.ref.uri);
                    const fallbackName = h.ref.name || h.ref.uri;
                    const dashIdx = !t ? fallbackName.indexOf(" - ") : -1;
                    const fallbackArtist = dashIdx > 0 ? fallbackName.slice(0, dashIdx) : "";
                    const fallbackTitle = dashIdx > 0 ? fallbackName.slice(dashIdx + 3) : fallbackName;
                    const title = t?.name ?? fallbackTitle;
                    const artist = t ? joinArtists(t) : fallbackArtist;
                    const album = t?.album?.name ?? "";
                    return (
                      <Row
                        key={h.ts + h.ref.uri + i}
                        title={title}
                        subtitle={artist + (album ? ` · ${album}` : "")}
                        meta={relativeTime(h.ts)}
                        onClick={() => { void playUris([h.ref.uri]).then(onClose); }}
                        icon="▶"
                        thumb={(artist || album) ? (
                          <AlbumThumb artist={artist} album={album} track={title} seed={h.ref.uri} size={40}/>
                        ) : null}
                      />
                    );
                  })
                : visibleTracks
                ? visibleTracks.map((t, i) => (
                    <Row
                      key={t.uri + i}
                      title={t.name || t.uri}
                      subtitle={joinArtists(t) || (t.album?.name ?? "")}
                      meta={t.length ? formatDuration(t.length) : ""}
                      onClick={() => playTrackAt(i)}
                      icon="▶"
                      thumb={(joinArtists(t) || t.album?.name) ? (
                        <AlbumThumb
                          artist={joinArtists(t)}
                          album={t.album?.name}
                          track={t.name}
                          seed={t.uri}
                          size={40}
                        />
                      ) : null}
                    />
                  ))
                : (items.length > 0 && items.every(r => r.type === "album"))
                ? (
                    <div style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
                      gap: 12,
                      padding: 12,
                      justifyItems: "center",
                    }}>
                      {items.map(r => (
                        <div
                          key={r.uri}
                          onClick={() => enterRef(r)}
                          style={{
                            cursor: "pointer",
                            display: "flex",
                            flexDirection: "column",
                            alignItems: "center",
                            gap: 8,
                            textAlign: "center",
                            width: "100%",
                            maxWidth: 160,
                            position: "relative",
                          }}
                        >
                          <AlbumThumb album={r.name} seed={r.uri} size={140} radius={8}/>
                          {/* Quick-play overlay button — tap to play the whole
                            * album immediately without drilling into tracks. */}
                          <button
                            onClick={(e) => { e.stopPropagation(); void playRefImmediate(r); }}
                            aria-label={`Play ${r.name}`}
                            style={{
                              position: "absolute",
                              right: 8, top: 8,
                              width: 38, height: 38,
                              borderRadius: 999,
                              background: "rgba(0,0,0,0.65)",
                              backdropFilter: "blur(6px)",
                              border: "1px solid rgba(255,255,255,0.25)",
                              color: "#fff",
                              cursor: "pointer",
                              fontSize: 14,
                              fontWeight: 700,
                              display: "grid",
                              placeItems: "center",
                            }}
                          >▶</button>
                          <div style={{
                            fontSize: 13, fontWeight: 600,
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                            paddingInline: 4,
                            width: "100%",
                          }}>{r.name}</div>
                        </div>
                      ))}
                    </div>
                  )
                : items.map(r => {
                    const isAlbum = r.type === "album";
                    const isArtist = r.type === "artist";
                    return (
                      <Row
                        key={r.uri}
                        title={r.name}
                        subtitle={r.type === "album" ? "Album" : r.type === "artist" ? "Artist" : r.type === "track" ? "Track" : "Folder"}
                        onClick={() => enterRef(r)}
                        icon={r.type === "track" ? "▶" : "›"}
                        thumb={(isAlbum || isArtist) ? (
                          <AlbumThumb
                            album={isAlbum ? r.name : undefined}
                            artist={isArtist ? r.name : undefined}
                            seed={r.uri}
                            size={40}
                          />
                        ) : null}
                      />
                    );
                  })}
              {searchActive && !searching && (searchResults?.length ?? 0) === 0 && (
                <div style={{padding: 24, fontFamily: "'JetBrains Mono', monospace", color: "rgba(255,255,255,0.5)"}}>
                  No matches for “{query}”.
                </div>
              )}
              {!searchActive && items.length === 0 && tracks === null && (
                <div style={{padding: 24, fontFamily: "'JetBrains Mono', monospace", color: "rgba(255,255,255,0.5)"}}>
                  Empty.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ title, subtitle, meta, onClick, icon, thumb }: {
  title: string; subtitle?: string; meta?: string;
  onClick: () => void; icon: string; thumb?: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%",
        textAlign: "left",
        background: "transparent",
        border: "none",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
        padding: "10px 16px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        color: "inherit",
        cursor: "pointer",
        minHeight: 60,
      }}
    >
      {thumb ?? (
        <div style={{
          width: 28, height: 28, borderRadius: 6,
          background: "rgba(255,255,255,0.06)",
          color: "rgba(255,255,255,0.7)",
          display: "grid", placeItems: "center",
          fontSize: 16, flexShrink: 0,
        }}>{icon}</div>
      )}
      <div style={{flex: 1, minWidth: 0}}>
        <div style={{
          fontSize: 15, fontWeight: 600,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>{title}</div>
        {subtitle && (
          <div style={{
            fontSize: 12, color: "rgba(255,255,255,0.55)",
            fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.04em",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            marginTop: 2,
          }}>{subtitle}</div>
        )}
      </div>
      {meta && (
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 12, color: "rgba(255,255,255,0.6)",
          flexShrink: 0,
        }}>{meta}</div>
      )}
    </button>
  );
}
