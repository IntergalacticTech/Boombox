import { useEffect, useState, type CSSProperties } from "react";
import { useApi, apiErrorMessage } from "../lib/api";
import type { Navigate } from "../lib/route";
import { AuthedImg } from "../components/AuthedImg";
import { SectionMessage } from "../components/SectionMessage";
import { SkeletonRows } from "../components/Skeleton";
import { TILE_GRID } from "../components/grid";
import { VideoControls } from "../components/VideoControls";
import {
  PAGE_SIZE, TICKS_PER_SECOND, clock, imagePath, isPlayable, itemSubtitle, itemsPath, typesFor,
  type VideoItem, type VideoPage,
} from "../lib/video";

const VIDEO_DOWN = "The video server isn't answering";
const SIGN_IN_HINT = "Sign the boombox screen in under Admin → Accounts → Video server.";

function hintFor(message: string): string | undefined {
  return message === "kiosk not signed in" ? SIGN_IN_HINT : undefined;
}

/** Jellyfin, browsed as the user the boombox screen is signed in as.
 *  #/video = home, #/video/lib/<id>/<collectionType>, #/video/folder/<id>. */
export function Video({ params, navigate }: { params: string[]; navigate: Navigate }) {
  const [a, b, c] = params;
  const [sheet, setSheet] = useState<VideoItem | null>(null);
  const open = (i: VideoItem) => {
    if (isPlayable(i)) setSheet(i);
    else if (i.collection_type) navigate("video", ["lib", i.id, i.collection_type]);
    else navigate("video", ["folder", i.id]);
  };
  return (
    <div style={{ padding: 16, paddingBottom: 96 }}>
      <VideoControls />
      {a === "lib" && b ? (
        <>
          <Back navigate={navigate} />
          <VideoGrid key={`lib/${b}`} parentId={b} types={typesFor(c)} onOpen={open} />
        </>
      ) : a === "folder" && b ? (
        <>
          <Back navigate={navigate} />
          <VideoGrid key={`folder/${b}`} parentId={b} types="" onOpen={open} />
        </>
      ) : (
        <VideoHome onOpen={open} />
      )}
      {sheet && <ItemSheet item={sheet} onClose={() => setSheet(null)} />}
    </div>
  );
}

function Back({ navigate }: { navigate: Navigate }) {
  return (
    <button type="button" onClick={() => navigate("video")} style={backBtn}>‹ Video</button>
  );
}

function VideoHome({ onOpen }: { onOpen: (i: VideoItem) => void }) {
  const api = useApi();
  const [views, setViews] = useState<VideoItem[] | null>(null);
  const [resume, setResume] = useState<VideoItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");

  useEffect(() => {
    let live = true;
    setError(null);
    Promise.all([
      api.get<{ items: VideoItem[] }>("api/remote/video/views"),
      api.get<{ items: VideoItem[] }>("api/remote/video/resume"),
    ]).then(([v, r]) => {
      if (!live) return;
      setViews(v.items ?? []);
      setResume(r.items ?? []);
    }).catch((e) => { if (live) setError(apiErrorMessage(e, VIDEO_DOWN)); });
    return () => { live = false; };
  }, [api, attempt]);

  useEffect(() => {
    const t = window.setTimeout(() => setTerm(search.trim().length >= 2 ? search.trim() : ""), 350);
    return () => window.clearTimeout(t);
  }, [search]);

  if (error) {
    return <SectionMessage title="Video" message={error} hint={hintFor(error)}
                           onRetry={() => setAttempt((n) => n + 1)} />;
  }
  if (!views) return <SkeletonRows count={6} />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <input type="search" aria-label="Search videos" value={search}
             onChange={(e) => setSearch(e.target.value)}
             placeholder="Search movies and shows…" style={searchInput} />
      {term ? (
        <VideoGrid key={`search/${term}`} search={term} types="Movie,Series,Episode" onOpen={onOpen} />
      ) : (
        <>
          {resume.length > 0 && (
            <section>
              <h2 style={h2}>Continue watching</h2>
              <div style={TILE_GRID}>
                {resume.map((i) => <Tile key={i.id} item={i} onOpen={onOpen} />)}
              </div>
            </section>
          )}
          <section>
            <h2 style={h2}>Libraries</h2>
            <div style={TILE_GRID}>
              {views.map((i) => <Tile key={i.id} item={i} onOpen={onOpen} />)}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function VideoGrid({ parentId, types, search, onOpen }: {
  parentId?: string; types: string; search?: string; onOpen: (i: VideoItem) => void;
}) {
  const api = useApi();
  const [items, setItems] = useState<VideoItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [next, setNext] = useState(0);  // server offset of the next page
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    let live = true;
    setError(null);
    api.get<VideoPage>(itemsPath({ parentId, types, search, start: 0 }))
      .then((p) => {
        if (!live) return;
        setItems(p.items ?? []);
        setTotal(p.total ?? 0);
        setNext((p.start ?? 0) + PAGE_SIZE);
      })
      .catch((e) => { if (live) setError(apiErrorMessage(e, VIDEO_DOWN)); });
    return () => { live = false; };
  }, [api, parentId, types, search, attempt]);

  const more = async () => {
    if (!items) return;
    setLoadingMore(true);
    try {
      const p = await api.get<VideoPage>(itemsPath({ parentId, types, search, start: next }));
      setItems([...items, ...(p.items ?? [])]);
      setTotal(p.total ?? total);
      setNext((p.start ?? next) + PAGE_SIZE);
    } catch (e) {
      setError(apiErrorMessage(e, VIDEO_DOWN));
    } finally {
      setLoadingMore(false);
    }
  };

  if (error) {
    return <SectionMessage message={error} hint={hintFor(error)}
                           onRetry={() => setAttempt((n) => n + 1)} />;
  }
  if (!items) return <SkeletonRows count={6} />;
  if (items.length === 0) return <p style={{ color: "var(--ink2)" }}>Nothing here.</p>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={TILE_GRID}>
        {items.map((i) => <Tile key={i.id} item={i} onOpen={onOpen} />)}
      </div>
      {next < total && (
        <button type="button" onClick={() => void more()} disabled={loadingMore} style={secondary}>
          {loadingMore ? "Loading…" : `Load more (${total - next} left)`}
        </button>
      )}
    </div>
  );
}

function Tile({ item, onOpen }: { item: VideoItem; onOpen: (i: VideoItem) => void }) {
  const sub = itemSubtitle(item);
  return (
    <button type="button" onClick={() => onOpen(item)} style={tileBtn}>
      <div style={{ position: "relative" }}>
        <AuthedImg path={imagePath(item)} alt=""
                   style={{ width: "100%", aspectRatio: "2 / 3", borderRadius: 10 }} />
        {item.progress != null && item.progress > 0 && (
          <div aria-hidden="true" style={{ position: "absolute", left: 6, right: 6, bottom: 6,
            height: 4, borderRadius: 2, background: "rgba(0,0,0,0.5)" }}>
            <div style={{ width: `${Math.min(100, item.progress)}%`, height: "100%",
                          borderRadius: 2, background: "var(--accent)" }} />
          </div>
        )}
      </div>
      <span style={{ fontWeight: 600, fontSize: 14, ...ellipsis }}>{item.name}</span>
      {sub && <span style={{ fontSize: 12, color: "var(--ink2)", ...ellipsis }}>{sub}</span>}
    </button>
  );
}

function ItemSheet({ item, onClose }: { item: VideoItem; onClose: () => void }) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const start = async (fromSeconds: number) => {
    setBusy(true);
    setMsg("Starting on the boombox…");
    try {
      await api.post("api/remote/video/play", fromSeconds > 0
        ? { item_id: item.id, start_ticks: fromSeconds * TICKS_PER_SECOND }
        : { item_id: item.id });
      onClose();
    } catch (e) {
      setMsg(apiErrorMessage(e, "Couldn't start it on the boombox"));
      setBusy(false);
    }
  };
  return (
    <div role="dialog" aria-label={item.name} onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: "100%", maxWidth: 520, maxHeight: "90vh", overflowY: "auto",
        background: "var(--panel)", border: "1px solid var(--rule)", borderRadius: 14,
        padding: 16, display: "flex", flexDirection: "column", gap: 12,
      }}>
        <div style={{ display: "flex", gap: 14, minWidth: 0 }}>
          <AuthedImg path={imagePath(item, 480)} alt=""
                     style={{ width: 120, aspectRatio: "2 / 3", borderRadius: 10, flexShrink: 0 }} />
          <div style={{ minWidth: 0 }}>
            <h2 style={{ margin: "0 0 6px", fontSize: 20 }}>{item.name}</h2>
            <div style={{ color: "var(--ink2)", fontSize: 13 }}>{itemSubtitle(item)}</div>
          </div>
        </div>
        {item.overview && <p style={{ margin: 0, fontSize: 14, lineHeight: 1.45 }}>{item.overview}</p>}
        <button type="button" onClick={() => void start(0)} disabled={busy} style={primary}>
          Play on the boombox</button>
        {item.resume_s > 0 && (
          <button type="button" onClick={() => void start(item.resume_s)} disabled={busy}
                  style={secondary}>Resume from {clock(item.resume_s)}</button>
        )}
        {msg && <p role="status" style={{ margin: 0, color: "var(--ink2)", fontSize: 14 }}>{msg}</p>}
        <button type="button" onClick={onClose} style={secondary}>Close</button>
      </div>
    </div>
  );
}

const ellipsis: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const h2: CSSProperties = { fontSize: 16, margin: "0 0 10px" };
const searchInput: CSSProperties = {
  padding: "10px 12px", borderRadius: 10, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 16, width: "100%",
};
const tileBtn: CSSProperties = {
  display: "flex", flexDirection: "column", gap: 6, minWidth: 0, padding: 0,
  background: "transparent", border: 0, color: "var(--ink)", textAlign: "left", cursor: "pointer",
};
const primary: CSSProperties = {
  padding: "13px 18px", borderRadius: 12, border: 0, minHeight: 48,
  background: "var(--accent)", color: "var(--bg)", fontSize: 16, fontWeight: 700, cursor: "pointer",
};
const secondary: CSSProperties = {
  padding: "12px 18px", borderRadius: 12, minHeight: 48, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 15, cursor: "pointer",
};
const backBtn: CSSProperties = {
  background: "transparent", border: 0, color: "var(--ink2)", fontSize: 14,
  cursor: "pointer", padding: "4px 0", marginBottom: 8,
};
