import { useEffect, useState } from "react";
import { useRemote } from "../state/store";
import { useApi } from "../lib/api";
import { IconButton } from "../components/IconButton";
import { QueueView } from "../components/QueueView";
import { Visualizer } from "../components/Visualizer";

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
  const api = useApi();
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

  // Seek bar — same optimistic pattern as volume. Hold the user's drag
  // position locally, send on release, clear when the next state push
  // confirms (which usually arrives within a second of `seek`).
  const livePosition = state?.track?.position_s ?? 0;
  const [pendingPosition, setPendingPosition] = useState<number | null>(null);
  useEffect(() => { setPendingPosition(null); }, [livePosition]);

  // Client-side position tick. The server pushes state on track / play
  // changes, not on every second elapsed, so without this the seek bar
  // would freeze between pushes. Resets whenever a fresh push lands or
  // the track changes; clamps at duration so it doesn't run past the end.
  const [tickedPos, setTickedPos] = useState<number>(livePosition);
  useEffect(() => { setTickedPos(livePosition); }, [livePosition]);
  const durSec = state?.track?.duration_s ?? 0;
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setTickedPos((p) => Math.min(durSec || Infinity, p + 1));
    }, 1000);
    return () => window.clearInterval(id);
  }, [playing, trackTitle, durSec]);

  const displayPos = pendingPosition ?? tickedPos;

  const commitSeek = (secs: number) => {
    command("seek", secs);
    // Hold pendingPosition for ~1s longer so the state push from the
    // server-side seek doesn't snap the slider back to its pre-seek value
    // during the round-trip.
    setPendingPosition(secs);
    setTickedPos(secs);  // jump the tick base too so it resumes from here
    window.setTimeout(() => setPendingPosition(null), 1200);
  };

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

      <div style={{ textAlign: "center", minHeight: 64, width: "100%" }}>
        {track
          ? <>
              <div style={{ fontSize: 22, fontWeight: 800 }}>
                {track.title ?? "Untitled"}
              </div>
              <div style={{ color: "var(--ink2)", marginTop: 4 }}>
                {[track.artist, track.album].filter(Boolean).join(" · ") || " "}
              </div>
              <div style={{ marginTop: 8, display: "flex",
                            alignItems: "center", gap: 8,
                            fontFamily: "var(--mono)", fontSize: 12,
                            color: "var(--ink2)" }}>
                <span style={{ width: 38, textAlign: "right" }}>
                  {mmss(displayPos)}
                </span>
                <input
                  aria-label="Seek"
                  type="range" min={0}
                  max={Math.max(1, track.duration_s)}
                  step={1}
                  value={displayPos}
                  onChange={(e) =>
                    setPendingPosition(Number(e.target.value))}
                  onMouseUp={(e) => commitSeek(
                    Number((e.target as HTMLInputElement).value))}
                  onTouchEnd={(e) => commitSeek(
                    Number((e.target as HTMLInputElement).value))}
                  onKeyUp={(e) => {
                    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                      commitSeek(Number((e.target as HTMLInputElement).value));
                    }
                  }}
                  style={{ flex: 1, accentColor: "var(--accent)" }}
                  disabled={!track.duration_s}
                />
                <span style={{ width: 38, textAlign: "left" }}>
                  {mmss(track.duration_s)}
                </span>
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

      {/* Live spectrum from boombox-audio's /audio/ws. Only enabled
          while audio is playing — otherwise we'd waste a WS connection
          and animate noise. */}
      <Visualizer base={api.base} enabled={playing} />

      {/* The queue refreshes whenever the current track or play state
          changes — every state push from the boombox bumps a counter so
          the inline list re-fetches without a manual reload. */}
      <QueueView refreshKey={queueRefreshKey} />
    </div>
  );
}
