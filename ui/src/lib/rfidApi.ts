// rfidApi — typed client for the boombox-rfid service (port 6688,
// fronted by nginx at /api/rfid/*). Mirrors libraryApi.ts.

export type BindingKind = "album" | "artist" | "playlist" | "track";

export type Binding = {
  uid: string;
  kind: BindingKind;
  target_id: string;
  label: string | null;
  added_at: number;
  last_tap_ts: number | null;
  tap_count: number;
};

export type RfidStatus = {
  service_version: string;
  device_path: string;
  last_tap_uid: string;
  last_tap_ts: number;
};

export type RecentTap = {
  uid: string;       // empty string when no recent unbound tap
  ts: number;
};

async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = (await r.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error || `HTTP ${r.status}`);
  }
  return (await r.json()) as T;
}

export async function getStatus(): Promise<RfidStatus> {
  return jsonOrThrow(await fetch("/api/rfid/status"));
}

export async function getRecent(): Promise<RecentTap> {
  return jsonOrThrow(await fetch("/api/rfid/recent"));
}

export async function listBindings(): Promise<Binding[]> {
  const body = await jsonOrThrow<{ bindings: Binding[] }>(
    await fetch("/api/rfid/bindings"),
  );
  return body.bindings;
}

export async function bind(
  uid: string, kind: BindingKind, targetId: string, label?: string | null,
): Promise<void> {
  await jsonOrThrow(await fetch("/api/rfid/bind", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uid, kind, target_id: targetId, label: label ?? null }),
  }));
}

export async function unbind(uid: string): Promise<void> {
  await jsonOrThrow(await fetch(`/api/rfid/bind/${encodeURIComponent(uid)}`, {
    method: "DELETE",
  }));
}
