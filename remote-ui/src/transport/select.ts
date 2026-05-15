import { HttpTransport } from "./HttpTransport";
import type { Transport } from "./types";

/** True when this browser can do Web Bluetooth at all. False on iOS Safari
 *  (no `navigator.bluetooth`), so the PWA never offers BLE there. */
export function bleAvailable(): boolean {
  return typeof navigator !== "undefined" && "bluetooth" in navigator;
}

/** Build the default (HTTP) transport. BLE transports are built by the
 *  pairing flow once a GATT connection exists — see Task 7 / Phase 2B. */
export function makeHttpTransport(base: string, token: string): Transport {
  return new HttpTransport(base, token);
}
