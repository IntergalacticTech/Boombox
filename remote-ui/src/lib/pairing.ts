const STORAGE_KEY = "boombox-remote-pairing";

export interface Pairing {
  base: string;   // e.g. "http://pi:8090"
  token: string;  // bearer token from /api/remote/pair
  name: string;   // boombox display name
}

export type RedeemResult =
  | { ok: true; token: string; name: string }
  | { ok: false; error: string };

/** Read the persisted pairing, or null. The token is durable — Phase 1's
 *  boombox-remote keeps it in peers.json across reboots. */
export function loadPairing(): Pairing | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw);
    if (p && typeof p.base === "string" && typeof p.token === "string") {
      return { base: p.base, token: p.token, name: p.name ?? "Boombox" };
    }
  } catch {
    /* fall through */
  }
  return null;
}

export function savePairing(p: Pairing): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
}

export function clearPairing(): void {
  localStorage.removeItem(STORAGE_KEY);
}

/** Redeem a 6-digit PIN for a durable bearer token via POST /api/remote/pair.
 *  `base` is the boombox LAN origin (e.g. "http://192.168.1.5:8090"). */
export async function redeemPin(
  base: string, pin: string, label: string,
): Promise<RedeemResult> {
  const origin = base.replace(/\/$/, "");
  try {
    const r = await fetch(`${origin}/api/remote/pair`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin, label }),
    });
    const body = await r.json().catch(() => ({}));
    if (body?.ok && body.auth_token) {
      return {
        ok: true,
        token: body.auth_token as string,
        name: (body.boombox_name as string) ?? "Boombox",
      };
    }
    return { ok: false, error: (body?.error as string) ?? "pair_failed" };
  } catch {
    return { ok: false, error: "unreachable" };
  }
}
