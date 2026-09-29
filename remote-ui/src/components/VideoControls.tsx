import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { useApi, apiErrorMessage } from "../lib/api";
import { useRemote } from "../state/store";
import { clock, type VideoState } from "../lib/video";

const btn: CSSProperties = {
  minWidth: 44, height: 44, borderRadius: 22, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 14, cursor: "pointer",
  padding: "0 12px",
};
const select: CSSProperties = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 16, maxWidth: "100%",
};

/** Controls for the video playing on the boombox's screen: title, time,
 *  ±30 s, play/pause, stop, scrubber, audio + subtitle tracks, volume.
 *  Polls /video/state while mounted; hidden when nothing is playing. */
export function VideoControls({ pollMs = 2000 }: { pollMs?: number }) {
  const api = useApi();
  const { state: remote, command: remoteCommand } = useRemote();
  const [st, setSt] = useState<VideoState | null>(null);
  const [pos, setPos] = useState(0);
  const [scrub, setScrub] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // /video/state can take up to 15 s, so refreshes are single-flight: while
  // one is in flight, further requests (poll or post-command) just mark it
  // dirty and exactly one follow-up runs after it settles. `gen` is bumped
  // by every command; an answer to a request started under an older gen is
  // stale (e.g. from before a seek) and is dropped instead of snapping the
  // clock/scrubber back.
  const inflight = useRef<Promise<void> | null>(null);
  const dirty = useRef(false);
  const gen = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const refresh = useCallback((): Promise<void> => {
    if (inflight.current) {
      dirty.current = true;
      return inflight.current;
    }
    const run = async () => {
      try {
        do {
          dirty.current = false;
          const started = gen.current;
          try {
            const s = await api.get<VideoState>("api/remote/video/state");
            if (started === gen.current && mounted.current) {
              setSt(s);
              setPos(s.position_s ?? 0);
            }
          } catch {
            /* keep the last state; the next poll retries */
          }
        } while (dirty.current && mounted.current);
      } finally {
        inflight.current = null;
      }
    };
    inflight.current = run();
    return inflight.current;
  }, [api]);

  useEffect(() => {
    let live = true;
    let timer: number | undefined;
    const loop = async () => {
      await refresh();
      if (live) timer = window.setTimeout(loop, pollMs);
    };
    void loop();
    return () => { live = false; window.clearTimeout(timer); };
  }, [refresh, pollMs]);

  // Tick the clock locally between polls while playing.
  useEffect(() => {
    if (!st?.active || !st.playing) return;
    const dur = st.duration_s || Infinity;
    const id = window.setInterval(() => setPos((p) => Math.min(dur, p + 1)), 1000);
    return () => window.clearInterval(id);
  }, [st]);

  if (!st?.active) return null;

  const send = async (action: string, value?: number) => {
    setError(null);
    gen.current += 1;  // state requested before this command is now stale
    try {
      await api.post("api/remote/video/command",
        value === undefined ? { action } : { action, value });
    } catch (e) {
      setError(apiErrorMessage(e, "The boombox didn't take that"));
    }
    gen.current += 1;  // …and so is anything requested while it was being applied
    void refresh();
  };
  const dur = st.duration_s ?? 0;
  const seekTo = (s: number) => {
    const v = Math.max(0, Math.round(dur ? Math.min(dur, s) : s));
    setPos(v);
    void send("seek", v);
  };
  const commitScrub = () => {
    if (scrub !== null) { seekTo(scrub); setScrub(null); }
  };
  const audio = st.audio_streams ?? [];
  const subs = st.subtitle_streams ?? [];

  return (
    <section aria-label="Video playing on the boombox" style={{
      border: "1px solid var(--rule)", borderRadius: 14, padding: 14, marginBottom: 16,
      display: "flex", flexDirection: "column", gap: 10, background: "var(--panel)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, minWidth: 0 }}>
        <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {st.title ?? "Video"}</strong>
        <span style={{ fontVariantNumeric: "tabular-nums", color: "var(--ink2)", flexShrink: 0 }}>
          {clock(scrub ?? pos)} / {clock(dur)}</span>
      </div>
      <input type="range" aria-label="Position" min={0} max={Math.max(dur, 1)} step={1}
             value={scrub ?? pos}
             onChange={(e) => setScrub(Number(e.target.value))}
             onPointerUp={commitScrub} onKeyUp={commitScrub}
             style={{ width: "100%" }} />
      <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
        <button type="button" aria-label="Back 30 seconds" onClick={() => seekTo(pos - 30)}
                style={btn}>−30 s</button>
        <button type="button" aria-label={st.playing ? "Pause video" : "Play video"}
                onClick={() => void send("play_pause")}
                style={{ ...btn, background: "var(--accent)", color: "var(--bg)", border: 0 }}>
          {st.playing ? "❚❚" : "▶"}</button>
        <button type="button" aria-label="Forward 30 seconds" onClick={() => seekTo(pos + 30)}
                style={btn}>+30 s</button>
        <button type="button" aria-label="Stop video" onClick={() => void send("stop")}
                style={btn}>■</button>
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {audio.length > 0 && (
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
            Audio
            <select aria-label="Audio track" value={String(st.audio_index ?? audio[0].index)}
                    onChange={(e) => void send("set_audio", Number(e.target.value))} style={select}>
              {audio.map((a) => <option key={a.index} value={String(a.index)}>{a.label}</option>)}
            </select>
          </label>
        )}
        {subs.length > 0 && (
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
            Subtitles
            <select aria-label="Subtitles" value={String(st.subtitle_index ?? -1)}
                    onChange={(e) => void send("set_subtitle", Number(e.target.value))} style={select}>
              <option value="-1">Off</option>
              {subs.map((s) => <option key={s.index} value={String(s.index)}>{s.label}</option>)}
            </select>
          </label>
        )}
      </div>
      <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
        Volume
        <input type="range" aria-label="Boombox volume" min={0} max={1} step={0.01}
               value={remote?.volume ?? 0}
               onChange={(e) => void remoteCommand("volume", Number(e.target.value))}
               style={{ flex: 1, minWidth: 0 }} />
      </label>
      {error && <div role="alert" style={{ color: "#ff7878", fontSize: 13 }}>{error}</div>}
    </section>
  );
}
