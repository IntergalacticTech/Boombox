import { useEffect, useState } from "react";
import { useApi, ApiError } from "../lib/api";
import { SkeletonRows } from "../components/Skeleton";

interface Ref {
  uri: string;
  name: string;
  type: "directory" | "album" | "artist" | "track" | "playlist";
}

interface Crumb { uri: string | null; name: string; }

function refIcon(t: Ref["type"]): string {
  switch (t) {
    case "artist":   return "👤";
    case "album":    return "💿";
    case "track":    return "🎵";
    case "playlist": return "≡";
    case "directory":
    default:         return "📁";
  }
}

/** Mopidy-backed library browser: drill from backends → artists → albums
 *  → tracks. Each non-track row plays or drills; each track row plays just
 *  that track. Maintains a breadcrumb stack so the back button is always
 *  one tap. Mopidy's lookup() resolves an album / artist URI into its
 *  tracks — that's how "Play this album" works without a recursive walk. */
export function Library() {
  const api = useApi();
  const [stack, setStack] = useState<Crumb[]>([
    { uri: null, name: "Library" },
  ]);
  const [refs, setRefs] = useState<Ref[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const here = stack[stack.length - 1];

  useEffect(() => {
    let aborted = false;
    setBusy(true);
    setErr(null);
    const q = here.uri ? `?uri=${encodeURIComponent(here.uri)}` : "";
    api
      .get<{ ok: boolean; refs: Ref[] }>(`api/remote/library/browse${q}`)
      .then((r) => { if (!aborted) setRefs(r.refs); })
      .catch((e: unknown) => {
        if (aborted) return;
        setErr(e instanceof ApiError ? `${e.status}` : "failed");
      })
      .finally(() => { if (!aborted) setBusy(false); });
    return () => { aborted = true; };
  }, [here.uri, api]);

  const enter = (r: Ref) => setStack((s) => [...s, { uri: r.uri, name: r.name }]);
  const up = () => {
    if (stack.length <= 1) return;
    setStack((s) => s.slice(0, -1));
  };
  const jump = (i: number) => setStack((s) => s.slice(0, i + 1));

  const play = async (r: Ref, mode: "play" | "queue") => {
    setToast(null);
    try {
      let uris: string[];
      if (r.type === "track") {
        uris = [r.uri];
      } else {
        const looked = await api.get<{ ok: boolean; tracks: { uri: string }[] }>(
          `api/remote/library/lookup?uri=${encodeURIComponent(r.uri)}`,
        );
        uris = looked.tracks.map((t) => t.uri);
      }
      if (uris.length === 0) {
        setToast(`${r.name}: no playable tracks.`);
        return;
      }
      await api.post("api/remote/queue", { uris, play: mode === "play" });
      setToast(
        mode === "play"
          ? `Playing ${r.name} (${uris.length} track${uris.length === 1 ? "" : "s"}).`
          : `Queued ${r.name} (${uris.length} track${uris.length === 1 ? "" : "s"}).`,
      );
    } catch (e: unknown) {
      setToast(e instanceof ApiError ? `Failed (${e.status})` : "Failed");
    }
  };

  return (
    <div style={{ padding: 16, paddingBottom: 96 }}>
      <header style={{ display: "flex", alignItems: "center", gap: 8,
                       marginBottom: 12 }}>
        <button type="button" onClick={up} disabled={stack.length <= 1}
                aria-label="Up" style={iconBtn}>‹</button>
        <nav aria-label="Breadcrumbs" style={{
          flex: 1, minWidth: 0, fontSize: 13, color: "var(--ink2)",
          overflowX: "auto", whiteSpace: "nowrap",
        }}>
          {stack.map((c, i) => (
            <span key={i}>
              {i > 0 && <span style={{ margin: "0 6px" }}>›</span>}
              <button type="button"
                      onClick={() => jump(i)}
                      style={{
                        ...crumbBtn,
                        color: i === stack.length - 1
                          ? "var(--ink)" : "var(--ink2)",
                      }}>
                {c.name}
              </button>
            </span>
          ))}
        </nav>
      </header>

      {toast && (
        <div role="status" style={banner}>{toast}</div>
      )}
      {err && (
        <div role="alert" style={{ ...banner, color: "var(--accent2)" }}>
          Error: {err}
        </div>
      )}
      {busy && !refs && <SkeletonRows count={8} />}

      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {refs?.map((r) => (
          <li key={r.uri} style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "10px 4px", borderBottom: "1px solid var(--rule)",
          }}>
            <button type="button"
                    onClick={() => r.type === "track" ? play(r, "play") : enter(r)}
                    style={{ ...rowBtn, flex: 1, minWidth: 0 }}>
              <span style={{ marginRight: 8 }}>{refIcon(r.type)}</span>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap" }}>{r.name}</span>
            </button>
            <button type="button"
                    aria-label={`Play ${r.name}`}
                    onClick={() => play(r, "play")} style={smallBtn}>▶</button>
            {r.type !== "track" && (
              <button type="button"
                      aria-label={`Queue ${r.name}`}
                      onClick={() => play(r, "queue")} style={smallBtn}>+</button>
            )}
          </li>
        ))}
        {refs && refs.length === 0 && (
          <li style={{ padding: "16px 4px", color: "var(--ink2)" }}>
            Empty.
          </li>
        )}
      </ul>
    </div>
  );
}

const banner: React.CSSProperties = {
  padding: "8px 12px", marginBottom: 12, borderRadius: 8,
  background: "var(--panel)", color: "var(--ink2)", fontSize: 13,
};
const iconBtn: React.CSSProperties = {
  width: 36, height: 36, borderRadius: 18,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", cursor: "pointer", fontSize: 18,
};
const smallBtn: React.CSSProperties = {
  padding: "6px 10px", borderRadius: 6,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", fontSize: 13, cursor: "pointer",
};
const rowBtn: React.CSSProperties = {
  background: "transparent", border: 0, color: "var(--ink)",
  fontSize: 15, padding: "4px 0", cursor: "pointer",
  textAlign: "left", display: "flex", alignItems: "center",
};
const crumbBtn: React.CSSProperties = {
  background: "transparent", border: 0, padding: 0, fontSize: 13,
  cursor: "pointer",
};
