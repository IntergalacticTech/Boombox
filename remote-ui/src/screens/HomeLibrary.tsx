import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { useApi, apiErrorMessage } from "../lib/api";
import type { Navigate } from "../lib/route";
import { AuthedImg } from "../components/AuthedImg";
import { SectionMessage } from "../components/SectionMessage";
import { SkeletonRows } from "../components/Skeleton";
import { TILE_GRID } from "../components/grid";
import {
  KEEP_IDLE_POLL_MS, KEEP_POLL_MS, KEEP_STALL_POLLS, MAX_EXPANDED_TRACKS, STATUS_POLL_MS, artPath, artistTrackIds, browseHome,
  homeDetail, homeStatus, keepHome, offlineIds, playHome, searchHome, unkeepHome,
  type HomeAlbumDetail, type HomeArtistDetail, type HomeItem, type HomeKind,
  type HomeList, type HomePlaylistDetail, type HomeSearchResult, type HomeStatus,
  type HomeTrack, type KeepState,
} from "../lib/homeLibrary";

const PAGE = 120;
const LIBRARY_DOWN = "The Home Library isn't answering";
export const OFFLINE_BANNER = "Offline — showing kept music";
export const NOTHING_KEPT = "None of these tracks are on the boombox.";
const LISTS: { id: HomeList; label: string }[] = [
  { id: "albums", label: "Albums" }, { id: "artists", label: "Artists" },
  { id: "playlists", label: "Playlists" },
];

type Detail = HomeAlbumDetail | HomeArtistDetail | HomePlaylistDetail;
type PlayFn = (ids: string[] | (() => Promise<string[]>), mode: "play" | "queue",
               label: string) => Promise<void>;

function usePlay(offline: boolean): { toast: string | null; play: PlayFn } {
  const api = useApi();
  const [toast, setToast] = useState<string | null>(null);
  const play = useCallback<PlayFn>(async (ids, mode, label) => {
    setToast(mode === "play" ? `Starting ${label}…` : `Queueing ${label}…`);
    try {
      const all = typeof ids === "function" ? await ids() : ids;
      if (all.length === 0) { setToast(offline ? NOTHING_KEPT : `${label}: nothing to play.`); return; }
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
  }, [api, offline]);
  return { toast, play };
}

/** Home Library reachability. null = unknown (route failed / older server):
 *  treated as online — no banner, nothing dimmed. One failed check keeps the
 *  last answer so a transient failure doesn't flicker the banner; the
 *  second in a row falls back to unknown. */
function useHomeStatus(): HomeStatus | null {
  const api = useApi();
  const [status, setStatus] = useState<HomeStatus | null>(null);
  useEffect(() => {
    let live = true;
    let failures = 0;
    const load = () => {
      homeStatus(api)
        .then((s) => { if (live) { failures = 0; setStatus(s); } })
        .catch(() => {
          failures += 1;
          if (live && failures >= 2) setStatus(null);
        });
    };
    load();
    const t = window.setInterval(load, STATUS_POLL_MS);
    return () => { live = false; window.clearInterval(t); };
  }, [api]);
  return status;
}

function mmss(sec: number | null | undefined): string {
  const s = Math.max(0, Math.floor(sec ?? 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** `tile`: in a column (tile) layout, don't stretch to the tile's width;
 *  in a row the row's alignItems centers it. */
function NotOffline({ tile }: { tile?: boolean }) {
  return <span style={tile ? { ...notOfflineTag, alignSelf: "flex-start" } : notOfflineTag}>not offline</span>;
}

/** Home Library browser. Lists (albums / artists / playlists) and details
 *  (album / artist / playlist) are hash routes: #/music/home/<list> and
 *  #/music/home/<kind>/<id>, so the phone's back button walks back out.
 *  While the Home Library server is unreachable an Offline banner shows and
 *  music that isn't on the boombox is dimmed and can't be played. */
export function HomeLibrary({ params, navigate }: { params: string[]; navigate: Navigate }) {
  const status = useHomeStatus();
  const offline = status !== null && !status.online;
  const [a, b] = params;
  const isDetail = (a === "artist" || a === "album" || a === "playlist") && b;
  const list: HomeList = a === "artists" || a === "playlists" ? a : "albums";
  return (
    <>
      {offline && <div role="status" aria-label="Offline" style={offlineBanner}>{OFFLINE_BANNER}</div>}
      {isDetail
        ? <HomeDetail key={`${a}/${b}`} kind={a as HomeKind} id={b} navigate={navigate} offline={offline} />
        : <HomeBrowse key={list} list={list} navigate={navigate} offline={offline} />}
    </>
  );
}

function HomeBrowse({ list, navigate, offline }: { list: HomeList; navigate: Navigate; offline: boolean }) {
  const api = useApi();
  const [items, setItems] = useState<HomeItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [filter, setFilter] = useState("");
  const [results, setResults] = useState<HomeSearchResult[] | null>(null);
  const [shown, setShown] = useState(PAGE);
  const [kept, setKept] = useState<Set<string> | null>(null);
  const { toast, play } = usePlay(offline);

  useEffect(() => {
    let live = true;
    setError(null);
    browseHome(api, list)
      .then((r) => { if (live) setItems(r); })
      .catch((e) => { if (live) setError(apiErrorMessage(e, LIBRARY_DOWN)); });
    return () => { live = false; };
  }, [api, list, attempt]);

  useEffect(() => {
    if (!offline) { setKept(null); return; }
    let live = true;
    offlineIds(api)
      .then((r) => {
        if (!live) return;
        setKept(new Set(list === "albums" ? r.album_ids : list === "artists" ? r.artist_ids : r.playlist_ids));
      })
      .catch(() => { if (live) setKept(null); });
    return () => { live = false; };
  }, [api, list, offline]);

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

  const dim = (id: string) => kept !== null && !kept.has(id);
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
            {results.slice(0, 30).map((r) => {
              const dimmed = offline && r.offline === false;
              return (
                <li key={`${r.content_type}:${r.id}`} style={{ ...row, opacity: dimmed ? 0.45 : 1 }}>
                  <span aria-hidden="true" style={{ width: 20 }}>
                    {r.content_type === "track" ? "🎵" : r.content_type === "album" ? "💿" : "👤"}
                  </span>
                  <span style={{ flex: 1, minWidth: 0, ...ellipsis }}>{r.title}</span>
                  {dimmed && <NotOffline />}
                  {r.content_type === "track" ? (
                    <button type="button" aria-label={`Play ${r.title}`} style={smallBtn} disabled={dimmed}
                            onClick={() => void play([r.id], "play", r.title)}>▶</button>
                  ) : (
                    <button type="button" aria-label={`Open ${r.title}`} style={smallBtn}
                            onClick={() => navigate("music", ["home",
                              r.content_type === "artist" ? "artist" : "album", r.id])}>›</button>
                  )}
                </li>
              );
            })}
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
            <li key={p.id} style={{ ...row, opacity: dim(p.id) ? 0.45 : 1 }}>
              <button type="button" onClick={() => navigate("music", ["home", "playlist", p.id])}
                      style={{ ...rowBtn, flex: 1, minWidth: 0 }}>
                <span style={ellipsis}>{p.name}</span>
                {p.song_count != null && (
                  <span style={{ color: "var(--ink2)", fontSize: 12, flexShrink: 0 }}>
                    {p.song_count} tracks</span>
                )}
                {dim(p.id) && <NotOffline />}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div style={TILE_GRID}>
          {filtered.slice(0, shown).map((i) => (
            <button key={i.id} type="button" onClick={() => navigate("music", ["home", openKind, i.id])}
                    style={{ ...tileBtn, opacity: dim(i.id) ? 0.4 : 1 }}>
              <AuthedImg path={artPath(i.art_id)} alt=""
                         style={{ width: "100%", aspectRatio: "1", borderRadius: 10 }} />
              <span style={{ fontWeight: 600, fontSize: 14, ...ellipsis }}>{i.name}</span>
              {list === "albums" && i.year != null && (
                <span style={{ fontSize: 12, color: "var(--ink2)" }}>{i.year}</span>
              )}
              {dim(i.id) && <NotOffline tile />}
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

function progressText(k: KeepState): string {
  return k.tracks_total > 0 && k.tracks_present >= k.tracks_total
    ? `All ${k.tracks_total} on the boombox`
    : `${k.tracks_present} / ${k.tracks_total} on the boombox`;
}

function KeepToggle({ kind, id, keep, onChange }: {
  kind: HomeKind; id: string; keep: KeepState; onChange: (k: KeepState) => void;
}) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (keep.state === "starred") {
    return (
      <div style={keepRow}>
        <span>★ Starred in Navidrome — kept offline automatically</span>
        <span style={keepProgress}>{progressText(keep)}</span>
      </div>
    );
  }
  const kept = keep.state === "kept";
  const toggle = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = kept ? await unkeepHome(api, kind, id) : await keepHome(api, kind, id);
      onChange(r.keep);
    } catch (e) {
      setError(apiErrorMessage(e, kept ? "Couldn't stop keeping it" : "Couldn't keep it offline"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div style={keepRow}>
      <button type="button" role="switch" aria-checked={kept} aria-label="Keep offline"
              disabled={busy} onClick={() => void toggle()} style={kept ? keptBtn : moreBtn}>
        {kept ? "✓ Keep offline" : "Keep offline"}
      </button>
      {kept && <span style={keepProgress}>{progressText(keep)}</span>}
      {error && <span role="alert" style={{ color: "var(--accent2)", fontSize: 13 }}>{error}</span>}
    </div>
  );
}

function HomeDetail({ kind, id, navigate, offline }: {
  kind: HomeKind; id: string; navigate: Navigate; offline: boolean;
}) {
  const api = useApi();
  const [data, setData] = useState<Detail | null>(null);
  const [keep, setKeep] = useState<KeepState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const { toast, play } = usePlay(offline);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    homeDetail<Detail>(api, kind, id)
      .then((d) => { if (live) { setData(d); setKeep(d.keep ?? null); } })
      .catch((e) => { if (live) setError(apiErrorMessage(e, LIBRARY_DOWN)); });
    return () => { live = false; };
  }, [api, kind, id, attempt]);

  // A kept item still downloading: refresh its progress (and track marks)
  // every KEEP_POLL_MS. After KEEP_STALL_POLLS polls with no change (tracks
  // stuck in error / no_space, queue paused) slow to KEEP_IDLE_POLL_MS. A
  // change in tracks_present re-runs this effect, which starts fast again;
  // so does reopening the page (a new mount).
  const downloading = keep !== null && keep.state === "kept" && keep.tracks_present < keep.tracks_total;
  const present = keep?.tracks_present ?? null;
  useEffect(() => {
    if (!downloading) return;
    let live = true;
    let still = 0;
    let t: number | undefined;
    const schedule = () => {
      t = window.setTimeout(tick, still >= KEEP_STALL_POLLS ? KEEP_IDLE_POLL_MS : KEEP_POLL_MS);
    };
    const tick = () => {
      homeDetail<Detail>(api, kind, id)
        .then((d) => {
          if (!live) return;
          setData(d);
          setKeep(d.keep ?? null);
          // A change re-runs the effect (new `present`); this one just ends.
          if ((d.keep?.tracks_present ?? null) === present) still += 1;
        })
        .catch(() => { still += 1; /* keep showing the last progress */ })
        .finally(() => { if (live) schedule(); });
    };
    schedule();
    return () => { live = false; window.clearTimeout(t); };
  }, [api, kind, id, downloading, present]);

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
  const toggle = keep && <KeepToggle kind={kind} id={id} keep={keep} onChange={setKeep} />;

  if (kind === "artist") {
    const d = data as HomeArtistDetail;
    return (
      <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
        {back}
        <h1 style={{ margin: 0, fontSize: 24 }}>{d.artist.name}</h1>
        <Actions onPlay={() => void play(() => artistTrackIds(api, id, offline), "play", d.artist.name)}
                 onQueue={() => void play(() => artistTrackIds(api, id, offline), "queue", d.artist.name)} />
        {toggle}
        {toast && <div role="status" style={banner}>{toast}</div>}
        <div style={TILE_GRID}>
          {d.albums.map((al) => {
            const dimmed = offline && al.offline === false;
            return (
              <button key={al.id} type="button" onClick={() => navigate("music", ["home", "album", al.id])}
                      style={{ ...tileBtn, opacity: dimmed ? 0.4 : 1 }}>
                <AuthedImg path={artPath(al.art_id)} alt=""
                           style={{ width: "100%", aspectRatio: "1", borderRadius: 10 }} />
                <span style={{ fontWeight: 600, fontSize: 14, ...ellipsis }}>{al.name}</span>
                {al.year != null && <span style={{ fontSize: 12, color: "var(--ink2)" }}>{al.year}</span>}
                {dimmed && <NotOffline tile />}
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  const album = kind === "album" ? (data as HomeAlbumDetail).album : null;
  const title = album ? album.name : (data as HomePlaylistDetail).playlist.name;
  const tracks: HomeTrack[] = (data as HomeAlbumDetail | HomePlaylistDetail).tracks;
  const playable = (t: HomeTrack) => !offline || t.offline === true;
  const ids = tracks.filter(playable).map((t) => t.id);
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
      {toggle}
      {toast && <div role="status" style={banner}>{toast}</div>}
      <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {tracks.map((t, i) => {
          const dimmed = !playable(t);
          return (
            <li key={`${t.id}:${i}`} style={{ ...row, opacity: dimmed ? 0.45 : 1 }}>
              <span style={{ width: 24, color: "var(--ink2)", fontSize: 12 }}>{i + 1}</span>
              <span style={{ flex: 1, minWidth: 0, ...ellipsis }}>{t.title}</span>
              {dimmed && <NotOffline />}
              {t.duration ? <span style={{ color: "var(--ink2)", fontSize: 12 }}>{mmss(t.duration)}</span> : null}
              <button type="button" aria-label={`Play from ${t.title}`} style={smallBtn} disabled={dimmed}
                      onClick={() => void play(tracks.slice(i).filter(playable).map((x) => x.id), "play", title)}>▶</button>
              <button type="button" aria-label={`Queue ${t.title}`} style={smallBtn} disabled={dimmed}
                      onClick={() => void play([t.id], "queue", t.title)}>+Q</button>
            </li>
          );
        })}
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
const offlineBanner: CSSProperties = {
  margin: "12px 16px 0", padding: "8px 12px", borderRadius: 8, fontSize: 14, fontWeight: 600,
  background: "var(--panel)", color: "var(--ink)", border: "1px solid var(--accent)",
};
const notOfflineTag: CSSProperties = {
  fontSize: 11, color: "var(--ink2)", border: "1px solid var(--rule)", borderRadius: 999,
  padding: "1px 6px", flexShrink: 0,
};
const keepRow: CSSProperties = {
  display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", fontSize: 14, color: "var(--ink2)",
};
const keepProgress: CSSProperties = { fontSize: 13, color: "var(--ink2)" };
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
const keptBtn: CSSProperties = { ...moreBtn, borderColor: "var(--accent)", color: "var(--accent)" };
const backBtn: CSSProperties = {
  alignSelf: "flex-start", background: "transparent", border: 0, color: "var(--ink2)",
  fontSize: 14, cursor: "pointer", padding: "4px 0",
};
