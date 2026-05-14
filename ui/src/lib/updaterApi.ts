// ui/src/lib/updaterApi.ts — typed client for /api/update/* (port 6685, fronted
// by nginx). Mirrors the config + status surface of boombox_updater.api.

export type Channel = "stable" | "edge";

export type UpdaterConfig = {
  auto: boolean;
  channel: Channel;
  window_start: string;        // "HH:MM" 24h
  window_duration_min: number;
};

export type LastAttempt = {
  ts: number;
  ref: string;
  result: "ok" | "rolled_back" | "broken" | "skipped_playback"
        | "fetch_failed" | "build_failed" | "smoke_failed";
  error: string | null;
  log_path: string;
};

export type UpdaterStatus = UpdaterConfig & {
  installed_version: string;
  available_version: string;
  available_published_at: string;
  last_check_ts: number;
  state_machine: string;
  service_version: string;
  last_attempt: LastAttempt | null;
};

export async function getStatus(): Promise<UpdaterStatus> {
  const r = await fetch("/api/update/status");
  if (!r.ok) throw new Error(`status ${r.status}`);
  return r.json();
}

export async function saveConfig(cfg: UpdaterConfig): Promise<UpdaterConfig> {
  const r = await fetch("/api/update/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({ error: "save failed" }));
    throw new Error(body.error || `save failed (${r.status})`);
  }
  return r.json();
}

export async function check(): Promise<UpdaterStatus> {
  const r = await fetch("/api/update/check", { method: "POST" });
  if (!r.ok) throw new Error(`check ${r.status}`);
  return r.json();
}

export async function installNow(opts: { ref?: string; force?: boolean } = {}):
  Promise<{ result: string }> {
  const r = await fetch("/api/update/install", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  });
  if (!r.ok) throw new Error(`install ${r.status}`);
  return r.json();
}

export async function rollback(): Promise<{ result: string }> {
  const r = await fetch("/api/update/rollback", { method: "POST" });
  if (!r.ok) throw new Error(`rollback ${r.status}`);
  return r.json();
}

export async function fetchLog(n: number = 200): Promise<string> {
  const r = await fetch(`/api/update/log?n=${n}`);
  if (r.status === 404) return "(no install attempts yet)";
  if (!r.ok) throw new Error(`log ${r.status}`);
  return r.text();
}
