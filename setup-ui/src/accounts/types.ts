export type CardState = "ok" | "problem" | "unset" | "absent";
export interface CardStatus { state: CardState; detail: string }
export interface Summary { music: CardStatus; video: CardStatus; streaming: CardStatus; web: CardStatus }
export interface MusicInfo { url: string; username: string; configured: boolean; reachable: boolean;
  last_sync_ts: number | null; syncing: boolean; prune_deferred: unknown; error?: string }
export interface VideoInfo { mode: "builtin" | "remote"; base: string; key_set: boolean;
  kiosk_device_id: string; kiosk_user: string | null }
export interface JfUser { id: string; name: string; admin: boolean }
export interface Receiver { installed: boolean; active: boolean; name: string; password_set?: boolean }
export interface StreamingInfo { airplay: Receiver; spotify: Receiver }
export interface OkResult { ok: boolean; error?: string }
