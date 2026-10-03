import { useEffect, useState, type CSSProperties } from "react";
import { useRemote } from "../state/store";
import { QueueView } from "./QueueView";

const ellipsis: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const roundBtn: CSSProperties = {
  width: 40, height: 40, borderRadius: 20, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", cursor: "pointer", fontSize: 14,
};

/** Desktop right column: always-visible Now Playing + the live queue. */
export function NowPanel() {
  const { state, command } = useRemote();
  const track = state?.track ?? null;
  const playing = !!state?.playing;
  const title = track?.title ?? null;
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => { setRefreshKey((k) => k + 1); }, [title, playing]);
  const subtitle = [track?.artist, track?.album].filter(Boolean).join(" · ");

  return (
    <aside aria-label="Now playing panel" style={{
      borderLeft: "1px solid var(--rule)", overflowY: "auto", minWidth: 0,
      padding: 16, display: "flex", flexDirection: "column", gap: 12,
    }}>
      {state?.art_url
        ? <img src={state.art_url} alt="" style={{ width: "100%", aspectRatio: "1",
                                                   objectFit: "cover", borderRadius: 12 }} />
        : <div style={{ width: "100%", aspectRatio: "1", borderRadius: 12,
                        background: "var(--panel)" }} />}
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: 16, ...ellipsis }}>{title ?? "Nothing playing"}</div>
        {subtitle && <div style={{ color: "var(--ink2)", fontSize: 13, ...ellipsis }}>{subtitle}</div>}
      </div>
      <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
        <button type="button" aria-label="Previous" onClick={() => command("previous")}
                style={roundBtn}>‹‹</button>
        <button type="button" aria-label={playing ? "Pause" : "Play"}
                onClick={() => command("play_pause")}
                style={{ ...roundBtn, width: 48, height: 48, borderRadius: 24, border: 0,
                         background: "var(--accent)", color: "var(--bg)" }}>
          {playing ? "❚❚" : "▶"}
        </button>
        <button type="button" aria-label="Next" onClick={() => command("next")}
                style={roundBtn}>››</button>
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12,
                      color: "var(--ink2)" }}>
        Volume
        <input type="range" aria-label="Volume" min={0} max={1} step={0.01}
               value={state?.volume ?? 0}
               onChange={(e) => command("volume", Number(e.target.value))}
               style={{ flex: 1, minWidth: 0 }} />
      </label>
      <h3 style={{ margin: "8px 0 0", fontSize: 12, color: "var(--ink2)",
                   textTransform: "uppercase", letterSpacing: "0.06em" }}>Up next</h3>
      <QueueView refreshKey={refreshKey} />
    </aside>
  );
}
