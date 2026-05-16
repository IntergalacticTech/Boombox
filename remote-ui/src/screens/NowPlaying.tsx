import { useEffect, useState } from "react";
import { useRemote } from "../state/store";
import { IconButton } from "../components/IconButton";
import { QueueView } from "../components/QueueView";

function mmss(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const SOURCE_LABELS: Record<string, string> = {
  mopidy: "Library",
  airplay: "AirPlay",
  spotify: "Spotify",
  bluetooth: "Bluetooth",
  movies: "Movies",
};

/** The core remote: album art, current track, transport controls, volume. */
export function NowPlaying() {
  const { state, command } = useRemote();
  const track = state?.track ?? null;
  const playing = state?.playing ?? false;
  const liveVolume = state?.volume ?? 0;
  const [pendingVolume, setPendingVolume] = useState<number | null>(null);
  // Clear the optimistic override whenever a fresh state push arrives.
  useEffect(() => { setPendingVolume(null); }, [liveVolume]);
  const volume = pendingVolume ?? liveVolume;
  const sources = state?.sources_available ?? [];
  const activeSource = state?.source ?? null;
  const [sourceToast, setSourceToast] = useState<string | null>(null);

  // The queue's a separate REST fetch — kick it on every meaningful state
  // change (track swap, play/pause) so jumps from another remote propagate
  // without the user pulling-to-refresh. position_s changes every second
  // so we deliberately key on title + playing instead of the full track.
  const trackTitle = state?.track?.title ?? null;
  const playingFlag = state?.playing ?? false;
  const [queueRefreshKey, setQueueRefreshKey] = useState(0);
  useEffect(() => { setQueueRefreshKey((k) => k + 1); },
            [trackTitle, playingFlag]);

  const pickSource = (s: string) => {
    command("source", s);
    // Most source handlers navigate or overlay the kiosk Chromium — the
    // audio "active source" doesn't necessarily change (e.g. tapping
    // Library while AirPlay is streaming opens the Library view on the
    // boombox but AirPlay keeps playing). Confirm with a toast so the
    // tap feels alive even when state.source doesn't move.
    setSourceToast(`${SOURCE_LABELS[s] ?? s} opened on boombox screen.`);
    window.setTimeout(() => setSourceToast(null), 2500);
  };

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 20,
      padding: 24, paddingBottom: 96, maxWidth: 520, margin: "0 auto",
      alignItems: "center",
    }}>
      {sources.length > 0 && (
        <div style={{ width: "100%" }}>
          <div style={{
            fontSize: 11, color: "var(--ink2)", letterSpacing: "0.06em",
            textTransform: "uppercase", textAlign: "center", marginBottom: 6,
          }}>
            Boombox screen
          </div>
          <div role="group" aria-label="Source"
               style={{
                 display: "flex", gap: 6, flexWrap: "wrap",
                 justifyContent: "center", width: "100%",
               }}>
            {sources.map((s) => {
              const active = s === activeSource;
              return (
                <button
                  key={s} type="button"
                  aria-pressed={active}
                  onClick={() => pickSource(s)}
                  style={{
                    padding: "6px 12px", borderRadius: 999, fontSize: 12,
                    border: "1px solid var(--rule)",
                    background: active ? "var(--accent)" : "var(--panel)",
                    color: active ? "var(--bg)" : "var(--ink2)",
                    cursor: "pointer",
                  }}
                >
                  {SOURCE_LABELS[s] ?? s}
                </button>
              );
            })}
          </div>
          {sourceToast && (
            <div role="status" style={{
              marginTop: 8, padding: "6px 10px", borderRadius: 8,
              background: "var(--panel)", color: "var(--ink2)",
              fontSize: 12, textAlign: "center",
            }}>{sourceToast}</div>
          )}
        </div>
      )}

      <div style={{
        width: "min(70vw, 320px)", aspectRatio: "1",
        borderRadius: 16, background: "var(--panel)",
        border: "1px solid var(--rule)",
        display: "grid", placeItems: "center", overflow: "hidden",
      }}>
        {state?.art_url
          ? <img src={state.art_url} alt=""
                 style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          : <span style={{ color: "var(--ink2)", fontSize: 13 }}>no art</span>}
      </div>

      <div style={{ textAlign: "center", minHeight: 64 }}>
        {track
          ? <>
              <div style={{ fontSize: 22, fontWeight: 800 }}>
                {track.title ?? "Untitled"}
              </div>
              <div style={{ color: "var(--ink2)", marginTop: 4 }}>
                {[track.artist, track.album].filter(Boolean).join(" · ") || " "}
              </div>
              <div style={{
                color: "var(--ink2)", fontFamily: "var(--mono)",
                fontSize: 13, marginTop: 6,
              }}>
                {mmss(track.position_s)} / {mmss(track.duration_s)}
              </div>
            </>
          : <div style={{ color: "var(--ink2)", fontSize: 16 }}>
              Nothing playing
            </div>}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <IconButton label="Previous" onClick={() => command("previous")}>
          ‹‹
        </IconButton>
        <IconButton label={playing ? "Pause" : "Play"} primary
                    onClick={() => command("play_pause")}>
          {playing ? "❚❚" : "▶"}
        </IconButton>
        <IconButton label="Next" onClick={() => command("next")}>
          ››
        </IconButton>
        <IconButton label="Stop" onClick={() => command("stop")}>
          ■
        </IconButton>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12,
                    width: "100%" }}>
        <IconButton label={state?.muted ? "Unmute" : "Mute"}
                    onClick={() => command("mute")}>
          {state?.muted ? "🔇" : "🔊"}
        </IconButton>
        <input
          aria-label="Volume"
          type="range" min={0} max={1} step={0.01} value={volume}
          onChange={(e) => {
            const n = Number(e.target.value);
            setPendingVolume(n);
            command("volume", n);
          }}
          style={{ flex: 1, accentColor: "var(--accent)" }}
        />
        <span style={{ fontFamily: "var(--mono)", fontSize: 13,
                       color: "var(--ink2)", width: 38, textAlign: "right" }}>
          {Math.round(volume * 100)}%
        </span>
      </div>

      <div style={{ display: "flex", gap: 14 }}>
        <IconButton label="Shuffle" toggled={!!state?.shuffle}
                    onClick={() => command("shuffle")}>
          🔀
        </IconButton>
        <IconButton label="Repeat" toggled={!!state?.repeat && state.repeat !== "off"}
                    onClick={() => command("repeat")}>
          {state?.repeat === "one" ? "🔂" : "🔁"}
        </IconButton>
      </div>

      {/* The queue refreshes whenever the current track or play state
          changes — every state push from the boombox bumps a counter so
          the inline list re-fetches without a manual reload. */}
      <QueueView refreshKey={queueRefreshKey} />
    </div>
  );
}
