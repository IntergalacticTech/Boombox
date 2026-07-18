// Shapes returned by the /api/setup/* backend. See the API contract in the
// setup wizard spec — these mirror the server responses exactly.

export interface Identity {
  name: string;
  id: string;
  hostname: string;
}

export interface WifiStatus {
  present: boolean;
  connected: boolean;
  ssid: string;
  ip: string;
}

export interface MusicStatus {
  url: string;
  username: string;
  configured: boolean;
  reachable: boolean;
}

export interface VideoStatus {
  mode: "builtin" | "remote";
  base: string;
  has_key: boolean;
}

export interface RemotePeer {
  label: string;
  paired_at: string;
}

export interface RemoteStatus {
  enabled: boolean;
  peers: RemotePeer[];
}

export interface Status {
  service_version: string;
  complete: boolean;
  identity: Identity;
  wifi: WifiStatus;
  music: MusicStatus;
  video: VideoStatus;
  remote: RemoteStatus;
  skin: string | null;
}

export interface SessionResult {
  token: string;
  code: string;
  expires_at: string;
  url: string;
  base_url: string;
}

export interface RedeemResult {
  ok: boolean;
  token?: string;
  error?: string;
}

export interface IdentityResult {
  ok: boolean;
  name?: string;
  id?: string;
  hostname?: string;
  rename_host?: boolean;
  unified?: string[];
  reboot_required?: boolean;
  error?: string;
}

export interface WifiNetwork {
  ssid: string;
  signal: number;
  secured: boolean;
}

export interface WifiScanResult {
  ok: boolean;
  networks?: WifiNetwork[];
  no_wifi?: boolean;
  error?: string;
}

export interface WifiJoinResult {
  ok: boolean;
  connected?: boolean;
  ssid?: string;
  ip?: string;
  error?: string;
}

export interface MusicTestResult {
  ok: boolean;
  error?: string;
}

export interface OkResult {
  ok: boolean;
  error?: string;
}

export interface RemoteEnableResult {
  ok: boolean;
  enabled: boolean;
}

export interface RemotePairResult {
  ok: boolean;
  pin: string;
  expires_at: string;
}

export interface VideoResult {
  ok: boolean;
  mode?: "builtin" | "remote";
  error?: string;
}
