export type PauseReason = "offline" | "low_space" | "hot" | "streaming";
export interface StorageDrive {
  present: boolean; internal: boolean; mount_path: string | null;
  total_bytes: number | null; free_bytes: number | null; reserve_bytes: number;
  music_bytes: number; kept_tracks: number;
}
/** "card": bound to an RFID card (pins source "rfid"). starred_tracks /
 *  card_tracks are one aggregate row each for single starred / card-bound
 *  songs (id ""). */
export type KeptSource = "user" | "starred" | "card";
export interface KeptItem {
  kind: "album" | "artist" | "playlist" | "starred_tracks" | "card_tracks"; id: string; name: string;
  source: KeptSource; tracks_total: number; tracks_present: number; bytes: number;
}
export interface Downloads {
  active: boolean; queued: number; in_flight: { id: string; title: string }[];
  paused: PauseReason | null; failed: number; no_space: number;
}
export interface StorageOverview { drive: StorageDrive; kept: KeptItem[]; downloads: Downloads }
export interface Failure { ok: false; error?: string }
export interface RemoveResult { ok: true; removed_tracks: number; freed_bytes: number }
export interface RetryResult { ok: true; retried: number }
