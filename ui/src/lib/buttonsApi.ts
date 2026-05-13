// buttonsApi — typed client for the boombox-buttons HTTP API (port 6684,
// fronted by nginx at /api/buttons/*). The buttons service hot-reloads
// ~/.config/boombox/buttons.json whenever it changes on disk, so POSTing
// /api/buttons/config is enough to propagate edits to the running daemon.

export type PinRow = { pin: number | null; enabled: boolean };

export type ButtonsConfig = {
  long_press_ms: number;
  power_hold_ms: number;
  encoder_step: number;
  pins: Record<string, PinRow>;
  encoder: { pin_a: number | null; pin_b: number | null; pin_push: number | null; enabled: boolean };
};

export async function getConfig(): Promise<ButtonsConfig> {
  const r = await fetch("/api/buttons/config");
  if (!r.ok) throw new Error(`config GET failed: ${r.status}`);
  return r.json();
}

export async function saveConfig(cfg: ButtonsConfig): Promise<void> {
  const r = await fetch("/api/buttons/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!r.ok) throw new Error(`config POST failed: ${r.status}`);
}

export async function learn(action: string): Promise<{ ok: boolean; pin?: number; error?: string }> {
  const r = await fetch("/api/buttons/learn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  return r.json();
}

export async function test(action: string): Promise<void> {
  await fetch("/api/buttons/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}

export const ACTION_LABELS: Record<string, string> = {
  play_pause: "Play / Pause",
  stop: "Stop",
  previous: "Previous",
  next: "Next",
  shuffle: "Shuffle",
  repeat: "Repeat",
  sleep_timer: "Sleep timer",
  skin_cycle: "Skin cycle",
  library: "Library",
  airplay: "AirPlay",
  spotify: "Spotify",
  bluetooth: "Bluetooth",
  movies: "Movies",
  web: "Web",
  mic_karaoke: "Mic / Karaoke",
  record: "Record",
  power: "Power",
};
