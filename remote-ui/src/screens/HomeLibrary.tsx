import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { useApi, apiErrorMessage } from "../lib/api";
import type { Navigate } from "../lib/route";
import { AuthedImg } from "../components/AuthedImg";
import { SectionMessage } from "../components/SectionMessage";
import { SkeletonRows } from "../components/Skeleton";
import { TILE_GRID } from "../components/grid";
import {
  MAX_EXPANDED_TRACKS, artPath, artistTrackIds, browseHome, homeDetail, playHome, searchHome,
  type HomeAlbumDetail, type HomeArtistDetail, type HomeItem, type HomeKind,
  type HomeList, type HomePlaylistDetail, type HomeSearchResult, type HomeTrack,
} from "../lib/homeLibrary";

const PAGE = 120;
const LIBRARY_DOWN = "The Home Library isn't answering";
const LISTS: { id: HomeList; label: string }[] = [
  { id: "albums", label: "Albums" }, { id: "artists", label: "Artists" },
  { id: "playlists", label: "Playlists" },
];

type PlayFn = (ids: string[] | (() => Promise<string[]>), mode: "play" | "queue",
               label: string) => Promise<void>;

function usePlay(): { toast: string | null; play: PlayFn } {
  const api = useApi();
  const [toast, setToast] = useState<string | null>(null);
  const play = useCallback<PlayFn>(async (ids, mode, label) => {
    setToast(mode === "play" ? `Starting ${label}…` : `Queueing ${label}…`);
    try {
      const all = typeof ids === "function" ? await ids() : ids;
      if (all.length === 0) { setToast(`${label}: nothing to play.`); return; }
      // The play route takes at most 1000 ids; cap every play/queue (album,
      // playlist, play-from, artist) at the kiosk's 500 and say so.
      const capped = all.length > MAX_EXPANDED_TRACKS;
      const list = capped ? all.slice(0, MAX_EXPANDED_TRACKS) : all;
      const r = await playHome(api, list, mode);
      const n = `${r.count} track${r.count === 1 ? "" : "s"}`;
      const skipped = r.skipped ? ` (${r.skipped} not available offline)` : "";
      const verb = mode === "play" ? "Playing" : "Queued";
      const what = capped ? `the first ${MAX_EXPANDED_TRACKS} tracks of ${label}` : label;
      setToast(`${verb} ${what} — ${n}${skipped}.`);
    } catch (e) {
      setToast(apiErrorMessage(e, "Couldn't play that"));
    }
  }, [api]);
  return { toast, play };
}

function mmss(sec: number | null | undefined): string {
  const s = Math.max(0, Math.floor(sec ?? 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Home Library browser. Lists (albums / artists / playlists) and details
 *  (album / artist / playlist) are hash routes: #/music/home/<list> and
 *  #/music/home/<kind>/<id>, so the phone's back button walks back out. */
export function HomeLibrary({ params, navigate }: { params: string[]; navigate: Navigate }) {
  const [a, b] = params;
  if ((a === "artist" || a === "album" || a === "playlist") && b) {
    return <HomeDetail key={`${a}/${b}`} kind={a} id={b} navigate={navigate} />;
  }
  const list: HomeList = a === "artists" || a === "playlists" ? a : "albums";
  return <HomeBrowse key={list} list={list} navigate={navigate} />;
}

function HomeBrowse({ list, navigate }: { list: HomeList; navigate: Navigate }) {
  const api = useApi();
  const [items, setItems] = useState<HomeItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [filter, setFilter] = useState("");
  const [results, setResults] = useState<HomeSearchResult[] | null>(null);
  const [shown, setShown] = useState(PAGE);
  const { toast, play } = usePlay();

  useEffect(() => {
    let live = true;
    setError(null);
    browseHome(api, list)
      .then((r) => { if (live) setItems(r); })
      .catch((e) => { if (live) setError(apiErrorMessage(e, LIBRARY_DOWN)); });
    return () => { live = false; };
  }, [api, list, attempt]);

  useEffect(() => {
    const q = filter.trim();
    if (q.length < 2) { setResults(null); return; }
    let live = true;
    const t = window.setTimeout(() => {
      searchHome(api, q)
        .then((r) => { if (live) setResults(r); })
        .catch(() => { if (live) setResults([]); });
    }, 300);
    return () => { live = false; window.clearTimeout(t); };
  }, [api, filter]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!items) return [];
    return q ? items.filter((i) => i.name.toLowerCase().includes(q)) : items;
  }, [items, filter]);

  const openKind: HomeKind = list === "artists" ? "artist" : list === "albums" ? "album" : "playlist";

  return (
    <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
      <div role="tablist" aria-label="Home Library lists" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {LISTS.map((l) => (
          <button key={l.id} type="button" role="tab" aria-selected={l.id === list}
                  onClick={() => navigate("music", ["home", l.id])} style={pill(l.id === list)}>
            {l.label}
          </button>
        ))}
      </div>
      <input type="search" aria-label="Search the Home Library" value={filter}
             onChange={(e) => { setFilter(e.target.value); setShown(PAGE); }}
             placeholder="Search artists, albums, tracks…" style={searchInput} />
      {toast && <div role="status" style={banner}>{toast}</div>}
      {results && results.length > 0 && (
        <section aria-label="Search results">
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {results.slice(0, 30).map((r) => (
              <li key={`${r.content_type}:${r.id}`} style={row}>
                <span aria-hidden="true" style={{ width: 20 }}>
                  {r.content_type === "track" ? "🎵" : r.content_type === "album" ? "💿" : "👤"}
                </span>
                <span style={{ flex: 1, minWidth: 0, ...ellipsis }}>{r.title}</span>
                {r.content_type === "track" ? (
                  <button type="button" aria-label={`Play ${r.title}`} style={smallBtn}
                          onClick={() => void play([r.id], "play", r.title)}>▶</button>
                ) : (
                  <button type="button" aria-label={`Open ${r.title}`} style={smallBtn}
                          onClick={() => navigate("music", ["home",
                            r.content_type === "artist" ? "artist" : "album", r.id])}>›</button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {error ? (
        <SectionMessage message={error} onRetry={() => setAttempt((n) => n + 1)} />
      ) : !items ? (
        <SkeletonRows count={8} />
      ) : list === "playlists" ? (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {filtered.slice(0, shown).map((p) => (
            <li key={p.id} style={row}>
              <button type="button" onClick={() => navigate("music", ["home", "playlist", p.id])}
                      style={{ ...rowBtn, flex: 1, minWidth: 0 }}>
                <span style={ellipsis}>{p.name}</span>
                {p.song_count != null && (
                  <span style={{ color: "var(--ink2)", fontSize: 12, flexShrink: 0 }}>
                    {p.song_count} tracks</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div style={TILE_GRID}>
          {filtered.slice(0, shown).map((i) => (
            <button key={i.id} type="button" onClick={() => navigate("music", ["home", openKind, i.id])}
                    style={tileBtn}>
              <AuthedImg path={artPath(i.art_id)} alt=""
                         style={{ width: "100%", aspectRatio: "1", borderRadius: 10 }} />
              <span style={{ fontWeight: 600, fontSize: 14, ...ellipsis }}>{i.name}</span>
              {list === "albums" && i.year != null && (
                <span style={{ fontSize: 12, color: "var(--ink2)" }}>{i.year}</span>
              )}
            </button>
          ))}
        </div>
      )}
      {items && filtered.length > shown && (
        <button type="button" onClick={() => setShown((n) => n + PAGE)} style={moreBtn}>
          Show more ({filtered.length - shown} left)
        </button>
      )}
    </div>
  );
}

function HomeDetail({ kind, id, navigate }: { kind: HomeKind; id: string; navigate: Navigate }) {
  const api = useApi();
  const [data, setData] = useState<HomeAlbumDetail | HomeArtistDetail | HomePlaylistDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const { toast, play } = usePlay();

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    homeDetail<HomeAlbumDetail | HomeArtistDetail | HomePlaylistDetail>(api, kind, id)
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) setError(apiErrorMessage(e, LIBRARY_DOWN)); });
    return () => { live = false; };
  }, [api, kind, id, attempt]);

  const backList: HomeList = kind === "artist" ? "artists" : kind === "album" ? "albums" : "playlists";
  const back = (
    <button type="button" onClick={() => navigate("music", ["home", backList])} style={backBtn}>
      ‹ Home Library
    </button>
  );
  if (error) {
    return <div style={{ padding: 16 }}>{back}
      <SectionMessage message={error} onRetry={() => setAttempt((n) => n + 1)} /></div>;
  }
  if (!data) return <div style={{ padding: 16 }}>{back}<SkeletonRows count={8} /></div>;

  if (kind === "artist") {
    const d = data as HomeArtistDetail;
    return (
      <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
        {back}
        <h1 style={{ margin: 0, fontSize: 24 }}>{d.artist.name}</h1>
        <Actions onPlay={() => void play(() => artistTrackIds(api, id), "play", d.artist.name)}
                 onQueue={() => void play(() => artistTrackIds(api, id), "queue", d.artist.name)} />
        {toast && <div role="status" style={banner}>{toast}</div>}
        <div style={TILE_GRID}>
          {d.albums.map((al) => (
            <button key={al.id} type="button" onClick={() => navigate("music", ["home", "album", al.id])}
                    style={tileBtn}>
              <AuthedImg path={artPath(al.art_id)} alt=""
                         style={{ width: "100%", aspectRatio: "1", borderRadius: 10 }} />
              <span style={{ fontWeight: 600, fontSize: 14, ...ellipsis }}>{al.name}</span>
              {al.year != null && <span style={{ fontSize: 12, color: "var(--ink2)" }}>{al.year}</span>}
            </button>
          ))}
        </div>
      </div>
    );
  }

  const album = kind === "album" ? (data as HomeAlbumDetail).album : null;
  const title = album ? album.name : (data as HomePlaylistDetail).playlist.name;
  const tracks: HomeTrack[] = (data as HomeAlbumDetail | HomePlaylistDetail).tracks;
  const ids = tracks.map((t) => t.id);
  return (
    <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
      {back}
      <div style={{ display: "flex", gap: 16, alignItems: "flex-end", flexWrap: "wrap" }}>
        {album && <AuthedImg path={artPath(album.art_id, 480)} alt=""
                             style={{ width: 160, height: 160, borderRadius: 12, flexShrink: 0 }} />}
        <div style={{ minWidth: 0, flex: 1 }}>
          <h1 style={{ margin: 0, fontSize: 24 }}>{title}</h1>
          {album && (album.artist || album.year) && (
            <div style={{ color: "var(--ink2)" }}>
              {[album.artist, album.year].filter(Boolean).join(" · ")}</div>
          )}
        </div>
      </div>
      <Actions onPlay={() => void play(ids, "play", title)} onQueue={() => void play(ids, "queue", title)} />
      {toast && <div role="status" style={banner}>{toast}</div>}
      <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {tracks.map((t, i) => (
          <li key={`${t.id}:${i}`} style={row}>
            <span style={{ width: 24, color: "var(--ink2)", fontSize: 12 }}>{i + 1}</span>
            <span style={{ flex: 1, minWidth: 0, ...ellipsis }}>{t.title}</span>
            {t.duration ? <span style={{ color: "var(--ink2)", fontSize: 12 }}>{mmss(t.duration)}</span> : null}
            <button type="button" aria-label={`Play from ${t.title}`} style={smallBtn}
                    onClick={() => void play(ids.slice(i), "play", title)}>▶</button>
            <button type="button" aria-label={`Queue ${t.title}`} style={smallBtn}
                    onClick={() => void play([t.id], "queue", t.title)}>+Q</button>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Actions({ onPlay, onQueue }: { onPlay: () => void; onQueue: () => void }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <button type="button" onClick={onPlay} style={primaryBtn}>Play all</button>
      <button type="button" onClick={onQueue} style={moreBtn}>Queue all</button>
    </div>
  );
}

const ellipsis: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const pill = (active: boolean): CSSProperties => ({
  padding: "6px 14px", borderRadius: 999, fontSize: 13, border: "1px solid var(--rule)",
  background: active ? "var(--accent)" : "var(--panel)",
  color: active ? "var(--bg)" : "var(--ink)", cursor: "pointer",
});
const searchInput: CSSProperties = {
  padding: "10px 12px", borderRadius: 10, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 16, width: "100%",
};
const banner: CSSProperties = {
  padding: "8px 12px", borderRadius: 8, background: "var(--panel)",
  color: "var(--ink2)", fontSize: 13,
};
const row: CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, padding: "10px 4px",
  borderBottom: "1px solid var(--rule)", minWidth: 0,
};
const rowBtn: CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, background: "transparent", border: 0,
  color: "var(--ink)", fontSize: 15, padding: "4px 0", cursor: "pointer", textAlign: "left",
};
const tileBtn: CSSProperties = {
  display: "flex", flexDirection: "column", gap: 6, minWidth: 0, padding: 0,
  background: "transparent", border: 0, color: "var(--ink)", textAlign: "left", cursor: "pointer",
};
const smallBtn: CSSProperties = {
  padding: "6px 10px", borderRadius: 6, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 13, cursor: "pointer", flexShrink: 0,
};
const primaryBtn: CSSProperties = {
  padding: "10px 18px", borderRadius: 10, border: 0, background: "var(--accent)",
  color: "var(--bg)", fontWeight: 700, fontSize: 15, cursor: "pointer",
};
const moreBtn: CSSProperties = {
  padding: "10px 18px", borderRadius: 10, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 15, cursor: "pointer",
};
const backBtn: CSSProperties = {
  alignSelf: "flex-start", background: "transparent", border: 0, color: "var(--ink2)",
  fontSize: 14, cursor: "pointer", padding: "4px 0",
};
