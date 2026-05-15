import type {
  Transport, RemoteState, CommandResult, ConnectionStatus,
} from "./types";

// WebSocket close codes from services/boombox-remote.py's _ws_handler.
const WS_BAD_TOKEN = 4401;
const WS_REMOTE_DISABLED = 4403;

/** Transport over the boombox-remote HTTP + WebSocket API. The default
 *  transport — works on every phone with LAN access to the boombox. */
export class HttpTransport implements Transport {
  readonly kind = "http" as const;

  private readonly base: string;          // e.g. "http://pi:8090"
  private readonly token: string;
  private ws: WebSocket | null = null;
  private stateCbs = new Set<(s: RemoteState) => void>();
  private statusCbs = new Set<(s: ConnectionStatus) => void>();

  constructor(base: string, token: string) {
    this.base = base.replace(/\/$/, "");
    this.token = token;
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const wsUrl = this.base.replace(/^http/, "ws") +
        `/api/remote/ws?token=${encodeURIComponent(this.token)}`;
      const ws = new WebSocket(wsUrl);
      this.ws = ws;
      ws.onopen = () => {
        this.emitStatus("connected");
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
        if (e.code === WS_REMOTE_DISABLED) this.emitStatus("disabled");
        else if (e.code === WS_BAD_TOKEN) this.emitStatus("unauthorized");
        else this.emitStatus("error");
        // If the socket closed before it ever opened, the connect() promise
        // is still pending — reject it so the caller sees the failure.
        reject(new Error(`ws closed: ${e.code}`));
      };
      ws.onerror = () => {
        this.emitStatus("error");
        reject(new Error("ws error"));
      };
    });
  }

  disconnect(): void {
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
      return (await r.json()) as CommandResult;
    } catch {
      return { ok: false, error: "unreachable" };
    }
  }

  private emitStatus(s: ConnectionStatus) {
    for (const cb of this.statusCbs) cb(s);
  }
}
