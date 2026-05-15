import type {
  Transport, RemoteState, CommandResult, ConnectionStatus,
} from "./types";

// GATT characteristic UUIDs — see services/ble_peripheral.py.
export const BLE_SERVICE_UUID = "0000bbbb-0000-1000-8000-00805f9b34fb";
export const BLE_STATE_UUID = "0000bbb3-0000-1000-8000-00805f9b34fb";
export const BLE_COMMAND_UUID = "0000bbb4-0000-1000-8000-00805f9b34fb";

/** Minimal structural type for the GATT characteristics this transport uses
 *  — keeps the class testable without the full BluetoothRemoteGATT* types. */
export interface BleChar {
  startNotifications(): Promise<unknown>;
  addEventListener(type: "characteristicvaluechanged",
                   cb: (e: Event) => void): void;
  writeValue(value: BufferSource): Promise<void>;
}

/** Transport over the boombox's BLE GATT peripheral. Android/Chrome only
 *  (Web Bluetooth). Constructed with already-resolved `state` and `command`
 *  characteristics — discovery + pairing happen in the pairing flow. */
export class BleTransport implements Transport {
  readonly kind = "ble" as const;

  private readonly stateChar: BleChar;
  private readonly commandChar: BleChar;
  private stateCbs = new Set<(s: RemoteState) => void>();
  private statusCbs = new Set<(s: ConnectionStatus) => void>();

  constructor(stateChar: BleChar, commandChar: BleChar) {
    this.stateChar = stateChar;
    this.commandChar = commandChar;
  }

  async connect(): Promise<void> {
    await this.stateChar.startNotifications();
    this.stateChar.addEventListener("characteristicvaluechanged", (e) => {
      const dv = (e.target as { value?: DataView }).value;
      if (!dv) return;
      try {
        const msg = JSON.parse(new TextDecoder().decode(dv));
        if (msg?.ok && msg.data) {
          for (const cb of this.stateCbs) cb(msg.data as RemoteState);
        }
      } catch {
        /* ignore malformed notify */
      }
    });
    this.emitStatus("connected");
  }

  disconnect(): void {
    // The GATT server lifecycle is owned by the pairing flow that created
    // this transport; nothing to tear down here beyond dropping callbacks.
    this.stateCbs.clear();
    this.statusCbs.clear();
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
    const body = value === undefined ? { action } : { action, value };
    try {
      await this.commandChar.writeValue(
        new TextEncoder().encode(JSON.stringify(body)),
      );
      // BLE command writes are fire-and-forget — the peripheral has no
      // per-command response characteristic. Callers MUST NOT treat
      // {ok: true} as confirmation the action took effect; observe the
      // next state push instead. (HttpTransport surfaces handler errors;
      // BLE cannot.)
      return { ok: true };
    } catch {
      return { ok: false, error: "unreachable" };
    }
  }

  private emitStatus(s: ConnectionStatus) {
    for (const cb of this.statusCbs) cb(s);
  }
}
