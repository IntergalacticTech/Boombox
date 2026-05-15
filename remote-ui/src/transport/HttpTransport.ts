import type {
  Transport, RemoteState, CommandResult, ConnectionStatus,
} from "./types";

// WebSocket close codes from services/boombox-remote.py's _ws_handler.
const WS_BAD_TOKEN = 4401;
const WS_REMOTE_DISABLED = 4403;
const WS_AGGREGATOR_UNAVAILABLE = 4503;

// Reconnect cadence: 1s, 2s, 4s, 8s, 16s, then capped at 30s. Phones
// suspend the WS aggressively when the screen sleeps; idle disconnects
// are normal, not user-visible failures.
const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 16000, 30000];

/** Transport over the boombox-remote HTTP + WebSocket API. The default
 *  transport — works on every phone with LAN access to the boombox. */
export class HttpTransport implements Transport {
  readonly kind = "http" as const;

  private readonly base: string;          // e.g. "http://pi:8090"
  private readonly token: string;
  private ws: WebSocket | null = null;
  private intentionalClose = false;
  private stateCbs = new Set<(s: RemoteState) => void>();
  private statusCbs = new Set<(s: ConnectionStatus) => void>();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(base: string, token: string) {
    this.base = base.replace(/\/$/, "");
    this.token = token;
  }

  connect(): Promise<void> {
    this.intentionalClose = false;
    return this._open(/* initial */ true);
  }

  disconnect(): void {
    this.intentionalClose = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  onState(cb: (s: RemoteState) => void): () => void {
    this.stateCbs.add(cb);
    return () => this.stateCbs.delete(cb);
  }

  onStatus(cb: (s: ConnectionStatus) => void): () => void {
    this.statusCbs.add(cb);
    return () => this.statusCbs.delete(cb);
  }

  async command(action: string, value?: unknown): Promise<CommandResult> {
    try {
      const r = await fetch(`${this.base}/api/remote/command`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.token}`,
        },
        body: JSON.stringify(
          value === undefined ? { action } : { action, value },
        ),
      });
      if (r.status === 403) return { ok: false, error: "remote_disabled" };
      if (r.status === 401) return { ok: false, error: "unauthorized" };
      if (!r.ok) return { ok: false, error: `http_${r.status}` };
      return (await r.json()) as CommandResult;
    } catch {
      return { ok: false, error: "unreachable" };
    }
  }

  private emitStatus(s: ConnectionStatus) {
    for (const cb of this.statusCbs) cb(s);
  }

  /** Open the socket. The returned promise rejects only on the *initial*
   *  attempt — subsequent reconnect attempts run silently so a sleeping
   *  phone doesn't surface a rejection the app already handled. */
  private _open(initial: boolean): Promise<void> {
    return new Promise((resolve, reject) => {
      const wsUrl = this.base.replace(/^http/, "ws") +
        `/api/remote/ws?token=${encodeURIComponent(this.token)}`;
      const ws = new WebSocket(wsUrl);
      this.ws = ws;
      let settled = false;
      ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.emitStatus("connected");
        settled = true;
        resolve();
      };
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg?.ok && msg.data) {
            for (const cb of this.stateCbs) cb(msg.data as RemoteState);
          }
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = (e) => {
        // A locally-initiated disconnect() fires onclose with code 1000;
        // don't translate that into a status banner or a reconnect attempt.
        if (this.intentionalClose) {
          if (!settled && initial) reject(new Error("ws closed during connect"));
          return;
        }
        // Terminal close codes — user action required; don't reconnect.
        if (e.code === WS_BAD_TOKEN) {
          this.emitStatus("unauthorized");
          if (!settled && initial) reject(new Error(`ws closed: ${e.code}`));
          return;
        }
        if (e.code === WS_REMOTE_DISABLED) {
          this.emitStatus("disabled");
          if (!settled && initial) reject(new Error(`ws closed: ${e.code}`));
          return;
        }
        // Recoverable: 4503 (aggregator restarting) and the generic
        // network closes (1006, idle timeouts, etc.) — schedule a retry.
        const status: ConnectionStatus =
          e.code === WS_AGGREGATOR_UNAVAILABLE ? "unavailable" : "connecting";
        this.emitStatus(status);
        this.scheduleReconnect();
        if (!settled && initial) {
          // Resolve the initial promise so the UI doesn't see the connect
          // as a hard failure — the status banner already says "connecting"
          // and the reconnect loop will take over.
          settled = true;
          resolve();
        }
      };
      ws.onerror = () => {
        // Most browsers fire onerror *and* onclose; let onclose own the
        // reconnect decision. Just surface the status if we're still in
        // the initial attempt.
        if (!settled && initial) this.emitStatus("connecting");
      };
    });
  }

  private scheduleReconnect(): void {
    if (this.intentionalClose) return;
    if (this.reconnectTimer !== null) return;
    const delay = RECONNECT_DELAYS_MS[
      Math.min(this.reconnectAttempts, RECONNECT_DELAYS_MS.length - 1)
    ];
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.intentionalClose) return;
      // Fire-and-forget: rejection is handled internally by onclose.
      this._open(false).catch(() => { /* surfaced via status */ });
    }, delay);
  }
}
