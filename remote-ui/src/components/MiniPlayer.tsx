import { useRemote } from "../state/store";

/** Persistent mini-player. Sits above the tab bar on every screen except
 *  Now Playing. Tapping the title strip switches the active tab to Now;
 *  the inline play/pause button avoids a round trip for the most common
 *  interaction. Hidden entirely when nothing is playing. */
export function MiniPlayer({ onOpenNow }: { onOpenNow: () => void }) {
  const { state, command } = useRemote();
  const track = state?.track ?? null;
  if (!track) return null;
  const playing = !!state?.playing;
  const subtitle = [track.artist, track.album].filter(Boolean).join(" · ");

  return (
    <div role="region" aria-label="Mini player"
         style={{
           position: "fixed",
           left: 0, right: 0,
           // The tab bar's own height + safe-area + a bit of gap. Phones
           // with home indicators get the inset from the tab bar's
           // env(safe-area-inset-bottom); the mini sits just above it.
           bottom: "calc(56px + env(safe-area-inset-bottom))",
           zIndex: 9,
           background: "var(--panel)",
           borderTop: "1px solid var(--rule)",
           display: "flex", alignItems: "center", gap: 10,
           padding: "8px 12px",
         }}>
      {state?.art_url
        ? <img src={state.art_url} alt=""
               style={{ width: 36, height: 36, borderRadius: 6,
                        objectFit: "cover", flexShrink: 0 }} />
        : <div style={{ width: 36, height: 36, borderRadius: 6,
                        background: "var(--bg)", flexShrink: 0 }} />}
      <button type="button"
              onClick={onOpenNow}
              aria-label="Open Now Playing"
              style={{
                flex: 1, minWidth: 0, textAlign: "left",
                background: "transparent", border: 0, color: "var(--ink)",
                cursor: "pointer", padding: 0,
              }}>
        <div style={{ fontSize: 13, fontWeight: 600,
                       overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>
          {track.title ?? "Untitled"}
        </div>
        {subtitle && (
          <div style={{ fontSize: 11, color: "var(--ink2)",
                         overflow: "hidden", textOverflow: "ellipsis",
                         whiteSpace: "nowrap" }}>
            {subtitle}
          </div>
        )}
      </button>
      <button type="button"
              aria-label={playing ? "Pause" : "Play"}
              onClick={() => command("play_pause")}
              style={{
                width: 38, height: 38, borderRadius: 19,
                border: 0, background: "var(--accent)", color: "var(--bg)",
                fontSize: 16, cursor: "pointer", lineHeight: 1, flexShrink: 0,
              }}>
        {playing ? "❚❚" : "▶"}
      </button>
      <button type="button"
              aria-label="Next"
              onClick={() => command("next")}
              style={{
                width: 36, height: 36, borderRadius: 18,
                border: "1px solid var(--rule)",
                background: "var(--panel)", color: "var(--ink)",
                fontSize: 14, cursor: "pointer", lineHeight: 1, flexShrink: 0,
              }}>
        ››
      </button>
    </div>
  );
}
