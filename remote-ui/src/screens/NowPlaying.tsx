import { useEffect, useState } from "react";
import { useRemote } from "../state/store";
import { IconButton } from "../components/IconButton";

function mmss(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

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

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 24,
      padding: 24, maxWidth: 520, margin: "0 auto", alignItems: "center",
    }}>
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
          type="range" min={0} max={100} value={volume}
          onChange={(e) => {
            const n = Number(e.target.value);
            setPendingVolume(n);
            command("volume", n);
          }}
          style={{ flex: 1, accentColor: "var(--accent)" }}
        />
        <span style={{ fontFamily: "var(--mono)", fontSize: 13,
                       color: "var(--ink2)", width: 38, textAlign: "right" }}>
          {volume}
        </span>
      </div>

      <IconButton label="Shuffle" onClick={() => command("shuffle")}>
        🔀
      </IconButton>
    </div>
  );
}
