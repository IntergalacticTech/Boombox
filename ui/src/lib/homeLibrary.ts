// homeLibrary — module-level pub/sub for the Phase 2 Home Library state
// (sync status, cache stats). Mirrors favorites.ts in shape; backed by
// periodic polling of /api/library/health + /api/library/cache/stats
// rather than localStorage (state lives server-side).
//
// Components subscribe via the React hooks; any apply*() call publishes
// to every subscriber so the chrome chip, the SettingsDrawer panels,
// the status badges on rows, etc. all stay in lockstep without each
// running its own poll.

import { useEffect, useState } from "react";
import {
  getCacheStats,
  getHealth,
  type CacheStats,
  type Health,
} from "./libraryApi";

export type SyncStatus = {
  reachable: boolean;
  lastSyncTs: number;
  syncing: boolean;
  cachePresent: boolean;
  cacheMount: string | null;
};

const EMPTY_SYNC: SyncStatus = {
  reachable: false, lastSyncTs: 0, syncing: false,
  cachePresent: false, cacheMount: null,
};

let _sync: SyncStatus = EMPTY_SYNC;
let _stats: CacheStats | null = null;

const _syncSubs = new Set<(s: SyncStatus) => void>();
const _statsSubs = new Set<(s: CacheStats | null) => void>();

let _pollHandle: number | null = null;
let _pollRefs = 0;          // ref-count: only one poll loop runs

function publishSync() {
  for (const s of _syncSubs) s(_sync);
}
function publishStats() {
  for (const s of _statsSubs) s(_stats);
}

export function applyHealth(h: Health): void {
  _sync = {
    reachable: h.navidrome_reachable,
    lastSyncTs: h.last_sync_ts,
    syncing: h.syncing,
    cachePresent: h.cache_present,
    cacheMount: h.cache_mount,
  };
  publishSync();
}

export function applyCacheStats(s: CacheStats | null): void {
  _stats = s;
  publishStats();
}

async function pollOnce(): Promise<void> {
  try { applyHealth(await getHealth()); } catch { /* leave previous */ }
  try { applyCacheStats(await getCacheStats()); } catch { applyCacheStats(null); }
}

function startPolling() {
  if (_pollHandle !== null) return;
  pollOnce();
  _pollHandle = window.setInterval(pollOnce, 5000);
}

function stopPolling() {
  if (_pollHandle !== null) {
    window.clearInterval(_pollHandle);
    _pollHandle = null;
  }
}

/** Subscribe to the global sync status. The poller starts on first
 * subscriber and stops when the last one unmounts (ref-counted). */
export function useSyncStatus(): SyncStatus {
  const [state, setState] = useState<SyncStatus>(_sync);
  useEffect(() => {
    const sub = (s: SyncStatus) => setState(s);
    _syncSubs.add(sub);
    _pollRefs += 1;
    if (_pollRefs === 1) startPolling();
    return () => {
      _syncSubs.delete(sub);
      _pollRefs -= 1;
      if (_pollRefs === 0) stopPolling();
    };
  }, []);
  return state;
}

/** Subscribe to current cache stats. Same ref-counted poll as useSyncStatus. */
export function useCacheStats(): CacheStats | null {
  const [state, setState] = useState<CacheStats | null>(_stats);
  useEffect(() => {
    const sub = (s: CacheStats | null) => setState(s);
    _statsSubs.add(sub);
    _pollRefs += 1;
    if (_pollRefs === 1) startPolling();
    return () => {
      _statsSubs.delete(sub);
      _pollRefs -= 1;
      if (_pollRefs === 0) stopPolling();
    };
  }, []);
  return state;
}

/** Force a single refresh (e.g., right after a Save in LibraryPanel). */
export function refreshNow(): Promise<void> {
  return pollOnce();
}

// Used by Vitest tests to reset between cases.
export function _resetForTests(): void {
  _sync = EMPTY_SYNC; _stats = null;
  _syncSubs.clear(); _statsSubs.clear();
  if (_pollHandle !== null) { window.clearInterval(_pollHandle); _pollHandle = null; }
  _pollRefs = 0;
}
