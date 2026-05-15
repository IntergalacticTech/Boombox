// The consolidated state payload from GET /api/remote/state and the WS push.
// Mirrors StateAggregator.consolidated_state() in services/boombox-remote.py.

export interface Track {
  title: string | null;
  artist: string | null;
  album: string | null;
  duration_s: number;
  position_s: number;
}

export interface ThemeVars {
  bg?: string;
  panel?: string;
  ink?: string;
  ink2?: string;
  accent?: string;
  accent2?: string;
  rule?: string;
  font?: string;
  mono?: string;
}

export interface RemoteState {
  boombox: { id: string; name: string; version: number };
  source: string | null;
  playing: boolean;
  track: Track | null;
  art_hash: string | null;
  art_url: string | null;
  volume: number | null;
  muted: boolean;
  sources_available: string[];
  sleep_timer_s: number | null;
  recording: boolean;
  mic_on: boolean;
  skin: string | null;
  theme: ThemeVars;
  shuffle?: boolean;
  repeat?: "off" | "all" | "one";
}

export interface CommandResult {
  ok: boolean;
  error?: string;
}

// Connection status surfaced to the UI. "disabled" = the boombox reported
// remote_disabled (the touchscreen toggle is off). "unavailable" = the
// boombox is reachable but the state aggregator is restarting (WS 4503).
export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "disabled"
  | "unauthorized"
  | "unavailable"
  | "error";

// Transport-agnostic contract. Both HttpTransport and BleTransport implement
// it; the UI never branches on `kind`. The library/playlists/video/files
// surface is HTTP-only and lives outside this interface (Phase 2B).
export interface Transport {
  readonly kind: "http" | "ble";
  // Establish the connection and begin state pushes. Rejects on a hard
  // failure (bad token, unreachable); resolves once connected.
  connect(): Promise<void>;
  disconnect(): void;
  // Subscribe to state pushes. Returns an unsubscribe function.
  onState(cb: (state: RemoteState) => void): () => void;
  // Subscribe to connection-status changes. Returns an unsubscribe function.
  onStatus?(cb: (status: ConnectionStatus) => void): () => void;
  // Fire a command. Resolves with the boombox's result.
  command(action: string, value?: unknown): Promise<CommandResult>;
}
