import { useEffect, useRef, useState } from "react";
import type { PlayState, Track } from "./types";
import { TRACKS, mmss } from "./shared";

type RpcCall = { id: number; resolve: (v: unknown) => void; reject: (e: unknown) => void };
type EventListener = (event: string, data: Record<string, unknown>) => void;

export class MopidyClient {
  private ws: WebSocket | null = null;
  private url: string;
  private nextId = 1;
  private pending = new Map<number, RpcCall>();
  private listeners = new Set<EventListener>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  connected = false;

  constructor(url?: string) {
    if (url) {
      this.url = url;
    } else {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      // Default to same-origin Mopidy WS endpoint.
      this.url = `${proto}//${window.location.host}/mopidy/ws`;
    }
  }

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    try {
      this.ws = new WebSocket(this.url);
    } catch (e) {
      console.warn("[mopidy] ws construct failed", e);
      this.scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      this.connected = true;
      this.emit("__connected", {});
    };
    this.ws.onclose = () => {
      this.connected = false;
      this.emit("__disconnected", {});
      this.scheduleReconnect();
    };
    this.ws.onerror = () => {
      // onclose will follow; reconnect handled there.
    };
    this.ws.onmessage = (ev) => {
      let msg: unknown;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (typeof msg !== "object" || msg === null) return;
      const m = msg as Record<string, unknown>;

      if (typeof m.id === "number" && (m.result !== undefined || m.error !== undefined)) {
        const call = this.pending.get(m.id);
        if (call) {
          this.pending.delete(m.id);
          if (m.error !== undefined) call.reject(m.error);
          else call.resolve(m.result);
        }
        return;
      }

      // Mopidy event envelopes look like:  { event: "track_playback_started", tl_track: {...} }
      if (typeof m.event === "string") {
        this.emit(m.event, m);
      }
    };
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, 1500);
  }

  private emit(event: string, data: Record<string, unknown>) {
    for (const l of this.listeners) {
      try { l(event, data); } catch (e) { console.warn("[mopidy] listener", e); }
    }
  }

  on(listener: EventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  rpc<T = unknown>(method: string, params?: Record<string, unknown> | unknown[]): Promise<T> {
    return new Promise((resolve, reject) => {
      const id = this.nextId++;
      const payload = JSON.stringify({ jsonrpc: "2.0", id, method, params: params ?? {} });
      this.pending.set(id, { id, resolve: resolve as (v: unknown) => void, reject });
      const send = () => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(payload);
        else setTimeout(send, 200);
      };
      send();
      // Time out hung requests.
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`mopidy rpc timeout: ${method}`));
        }
      }, 8000);
    });
  }
}

// ---------- React hook ----------------------------------------------------

export type MopidyState = {
  connected: boolean;
  track: Track | null;
  state: PlayState;
  positionMs: number;     // last known server position
  positionAtMs: number;   // local clock when positionMs was read
  volume: number | null;  // 0..100, null if unknown
  shuffle: boolean;
  repeat: boolean;        // tracklist-level repeat (any mode)
  play: () => void;
  pause: () => void;
  next: () => void;
  prev: () => void;
  toggle: () => void;
  setVolume: (v: number) => void;
  toggleShuffle: () => void;
  toggleRepeat: () => void;
  seek: (positionMs: number) => void;
};

type RawTlTrack = {
  track?: {
    uri?: string;
    name?: string;
    artists?: { name?: string }[];
    album?: { name?: string };
    length?: number;
  };
};

function rawToTrack(raw: RawTlTrack["track"] | null | undefined): Track | null {
  if (!raw) return null;
  const len = Math.floor((raw.length ?? 0) / 1000);
  const artist = (raw.artists ?? []).map(a => a?.name).filter(Boolean).join(", ") || "Unknown Artist";
  return {
    uri: raw.uri ?? "",
    title: raw.name ?? "Unknown Track",
    artist,
    album: raw.album?.name ?? "",
    time: mmss(len),
    len,
    hue: hueOf(raw.uri ?? raw.name ?? ""),
  };
}

function hueOf(seed: string): number {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = ((h << 5) - h + seed.charCodeAt(i)) | 0;
  return Math.abs(h) % 360;
}

const _client: MopidyClient | null = null;
let _clientHandle: MopidyClient | null = _client;
function getClient(): MopidyClient {
  if (!_clientHandle) {
    _clientHandle = new MopidyClient();
    _clientHandle.connect();
  }
  return _clientHandle;
}

export function useMopidy(opts: { fallback?: boolean } = { fallback: true }): MopidyState {
  const [connected, setConnected] = useState(false);
  const [track, setTrack] = useState<Track | null>(null);
  const [state, setState] = useState<PlayState>("stopped");
  const [positionMs, setPositionMs] = useState(0);
  const [positionAtMs, setPositionAtMs] = useState(Date.now());
  const [volume, setVolume] = useState<number | null>(null);
  const [shuffle, setShuffle] = useState(false);
  const [repeat, setRepeat] = useState(false);
  const clientRef = useRef<MopidyClient | null>(null);

  useEffect(() => {
    const client = getClient();
    clientRef.current = client;

    const refresh = async () => {
      try {
        const [cur, st, pos, vol, rnd, rep] = await Promise.all([
          client.rpc<RawTlTrack["track"] | null>("core.playback.get_current_track"),
          client.rpc<PlayState>("core.playback.get_state"),
          client.rpc<number>("core.playback.get_time_position"),
          client.rpc<number | null>("core.mixer.get_volume"),
          client.rpc<boolean>("core.tracklist.get_random"),
          client.rpc<boolean>("core.tracklist.get_repeat"),
        ]);
        setTrack(rawToTrack(cur));
        setState(st);
        setPositionMs(pos ?? 0);
        setPositionAtMs(Date.now());
        setVolume(vol ?? null);
        setShuffle(!!rnd);
        setRepeat(!!rep);
      } catch (e) {
        console.warn("[mopidy] refresh failed", e);
      }
    };

    const off = client.on((event, data) => {
      if (event === "__connected") {
        setConnected(true);
        refresh();
      } else if (event === "__disconnected") {
        setConnected(false);
      } else if (event === "track_playback_started" || event === "track_playback_resumed") {
        const tl = data.tl_track as RawTlTrack | undefined;
        if (tl?.track) setTrack(rawToTrack(tl.track));
        if (event === "track_playback_started") setState("playing");
        if (event === "track_playback_resumed") setState("playing");
        const tp = (data.time_position as number | undefined) ?? 0;
        setPositionMs(tp);
        setPositionAtMs(Date.now());
      } else if (event === "track_playback_paused") {
        setState("paused");
        const tp = (data.time_position as number | undefined) ?? 0;
        setPositionMs(tp);
        setPositionAtMs(Date.now());
      } else if (event === "track_playback_ended") {
        setState("stopped");
      } else if (event === "playback_state_changed") {
        const st = (data.new_state as PlayState | undefined) ?? "stopped";
        setState(st);
      } else if (event === "seeked") {
        const tp = (data.time_position as number | undefined) ?? 0;
        setPositionMs(tp);
        setPositionAtMs(Date.now());
      } else if (event === "volume_changed") {
        setVolume((data.volume as number | undefined) ?? null);
      } else if (event === "options_changed") {
        // Mopidy fires this without payload; re-read current values.
        client.rpc<boolean>("core.tracklist.get_random").then(v => setShuffle(!!v)).catch(() => {});
        client.rpc<boolean>("core.tracklist.get_repeat").then(v => setRepeat(!!v)).catch(() => {});
      }
    });

    if (client.connected) { setConnected(true); refresh(); }

    return off;
  }, []);

  // If Mopidy never connects, fall back to a demo track so the design has
  // something to render. Once we're connected, trust reality — show null when
  // there's no track instead of pretending a fake one is loaded.
  const fallback = opts.fallback !== false;
  const effectiveTrack = track ?? (fallback && !connected ? TRACKS[5] : null);

  const call = (method: string) => {
    const client = clientRef.current;
    if (!client) return;
    client.rpc(method).catch(() => {});
  };

  const setOption = (method: string, value: boolean) => {
    const client = clientRef.current;
    if (!client) return;
    client.rpc(method, { value }).catch(() => {});
  };

  return {
    connected,
    track: effectiveTrack,
    state,
    positionMs,
    positionAtMs,
    volume,
    shuffle,
    repeat,
    play: () => call("core.playback.play"),
    pause: () => call("core.playback.pause"),
    next: () => call("core.playback.next"),
    prev: () => call("core.playback.previous"),
    toggle: () => call(state === "playing" ? "core.playback.pause" : "core.playback.play"),
    setVolume: (v: number) => {
      const client = clientRef.current;
      if (!client) return;
      client.rpc("core.mixer.set_volume", { volume: Math.max(0, Math.min(100, Math.round(v))) }).catch(() => {});
    },
    toggleShuffle: () => setOption("core.tracklist.set_random", !shuffle),
    toggleRepeat: () => setOption("core.tracklist.set_repeat", !repeat),
    seek: (positionMs: number) => {
      const client = clientRef.current;
      if (!client) return;
      const target = Math.max(0, Math.round(positionMs));
      // Optimistic update so the bar settles instantly under the finger; the
      // next event from Mopidy reconciles if it landed elsewhere.
      setPositionMs(target);
      setPositionAtMs(Date.now());
      client.rpc("core.playback.seek", { time_position: target }).catch(() => {});
    },
  };
}

// Hook for a smoothly-tracked, ticking elapsed time in seconds.
export function useElapsed(state: PlayState, positionMs: number, positionAtMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (state !== "playing") return;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [state]);
  if (state === "playing") {
    return Math.max(0, (positionMs + (now - positionAtMs)) / 1000);
  }
  return Math.max(0, positionMs / 1000);
}
