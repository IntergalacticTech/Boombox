import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { ErrorText, SecondaryButton } from "./ui";
import { LockScreen } from "./LockScreen";
import { lock, useAdminSession } from "./session";
import { UNREACHABLE, ACCOUNTS_DESKTOP_COLUMNS } from "./AccountsSection";
import { adminFilesClient, storageApi } from "./storage/api";
import type { KeptItem, PauseReason, StorageOverview } from "./storage/types";
import { SectionMessage } from "../components/SectionMessage";
import { FileBrowser } from "../screens/Files";

export const STORAGE_POLL_MS = 5000;
export const PAUSED_TEXT: Record<PauseReason, string> = {
  streaming: "Paused while music streams from the Home Library.",
  hot: "Paused — the boombox is hot (70 °C or more); checking again every minute.",
  offline: "Paused — the Home Library server can't be reached.",
  low_space: "Stopped — free space is below the reserve.",
};
const KIND_LABEL: Record<KeptItem["kind"], string> = {
  album: "Album", artist: "Artist", playlist: "Playlist", starred_tracks: "Songs",
};

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) { v /= 1024; u += 1; }
  return `${u === 0 || v >= 100 ? Math.round(v) : v.toFixed(1)} ${units[u]}`;
}

function Panel({ title, wide, children }: { title: string; wide?: boolean; children: ReactNode }) {
  return (
    <section style={{ border: "1px solid var(--rule)", borderRadius: 14, padding: 16, minWidth: 0,
                      gridColumn: wide ? "1 / -1" : undefined }}>
      <h2 style={{ fontSize: 18, margin: "0 0 12px" }}>{title}</h2>
      {children}
    </section>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "4px 0" }}>
      <dt style={muted}>{k}</dt><dd style={{ margin: 0, textAlign: "right" }}>{v}</dd>
    </div>
  );
}

function Header() {
  return (
    <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
      <h1 style={{ fontSize: 24, margin: 0 }}>Storage</h1>
      <SecondaryButton aria-label="Lock admin" onClick={() => void lock()}
                       style={{ width: "auto", minHeight: 40, padding: "8px 14px" }}>🔒 Lock</SecondaryButton>
    </header>
  );
}

function StoragePanel({ desktop, extra }: { desktop: boolean; extra?: ReactNode }) {
  const [data, setData] = useState<StorageOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const inFlight = useRef(false);

  const refresh = useCallback(async () => {
    inFlight.current = true;
    try {
      const r = await storageApi.overview();
      if ("drive" in r) { setData(r); setError(null); }
      else setError(r.error || UNREACHABLE);
    } catch {
      setError(UNREACHABLE);
    } finally {
      inFlight.current = false;
    }
  }, []);

  // Polls only while mounted, and this panel is mounted only while unlocked
  // (a 401 clears the session → StorageSection swaps in the lock screen →
  // this effect's cleanup stops the timer). A tick is skipped while the
  // previous request is still out or the tab is in the background.
  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => {
      if (inFlight.current || document.hidden) return;
      void refresh();
    }, STORAGE_POLL_MS);
    return () => window.clearInterval(t);
  }, [refresh, attempt]);

  const remove = async (item: KeptItem) => {
    if (!window.confirm(`Remove ${item.name} from the boombox? Its downloaded songs are deleted (songs another kept item needs stay).`)) return;
    setBusy(true);
    try {
      const r = await storageApi.remove(item.kind, item.id);
      setNotice(r.ok ? `Removed ${item.name} — ${fmtBytes(r.freed_bytes)} freed.`
                     : (r.error || "Couldn't remove it."));
    } catch {
      setNotice(UNREACHABLE);
    }
    setBusy(false);
    void refresh();
  };

  const retry = async () => {
    setBusy(true);
    try {
      const r = await storageApi.retry();
      setNotice(r.ok ? `Retrying ${r.retried} download${r.retried === 1 ? "" : "s"}.`
                     : (r.error || "Couldn't retry."));
    } catch {
      setNotice(UNREACHABLE);
    }
    setBusy(false);
    void refresh();
  };

  if (!data) {
    return (
      <div style={page}>
        <Header />
        {error
          ? <SectionMessage message={error} onRetry={() => setAttempt((n) => n + 1)} />
          : <p style={muted}>Loading…</p>}
      </div>
    );
  }
  const { drive, downloads, kept } = data;
  const low = drive.present && drive.free_bytes != null && drive.free_bytes < drive.reserve_bytes;
  return (
    <div style={page}>
      <Header />
      {error && <ErrorText>{error}</ErrorText>}
      {notice && <div role="status" style={noticeStyle}>{notice}</div>}
      <div data-testid="storage-grid" style={{
        display: "grid", gap: 16, alignItems: "start",
        gridTemplateColumns: desktop ? ACCOUNTS_DESKTOP_COLUMNS : "minmax(0, 1fr)",
      }}>
        <Panel title="Drive">
          {!drive.present ? <p style={muted}>No music storage — downloads are off.</p> : (
            <dl style={{ margin: 0 }}>
              <Fact k="Where" v={drive.internal ? "Internal drive" : `USB drive at ${drive.mount_path ?? "?"}`} />
              <Fact k="Size" v={fmtBytes(drive.total_bytes)} />
              <Fact k="Free" v={fmtBytes(drive.free_bytes)} />
              <Fact k="Always kept free" v={fmtBytes(drive.reserve_bytes)} />
              <Fact k="Music on the boombox" v={`${fmtBytes(drive.music_bytes)} · ${drive.kept_tracks} tracks`} />
            </dl>
          )}
          {low && <ErrorText>Low space — downloads stop until more than {fmtBytes(drive.reserve_bytes)} is free.</ErrorText>}
        </Panel>
        <Panel title="Downloads">
          {!downloads.active ? (
            <p style={muted}>Downloads aren't running — no music storage or no music server set up.</p>
          ) : (
            <>
              <p style={muted}>{downloads.in_flight.length} downloading · {downloads.queued} queued</p>
              {downloads.in_flight.length > 0 && (
                <ul style={list}>{downloads.in_flight.map((t) => <li key={t.id}>⬇ {t.title}</li>)}</ul>
              )}
              {downloads.paused && <p role="note" style={pausedStyle}>{PAUSED_TEXT[downloads.paused]}</p>}
            </>
          )}
          {downloads.no_space > 0 && <p style={muted}>{downloads.no_space} skipped — not enough space</p>}
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <span style={muted}>{downloads.failed} failed</span>
            <SecondaryButton disabled={busy || downloads.failed + downloads.no_space === 0}
                             onClick={() => void retry()} style={smallBtn}>Retry failed</SecondaryButton>
          </div>
        </Panel>
        <Panel title="Kept offline" wide>
          {kept.length === 0 ? (
            <p style={muted}>Nothing kept yet — open an album in Music and tap Keep offline.</p>
          ) : (
            <ul style={list}>
              {kept.map((it) => (
                <li key={`${it.kind}:${it.id}`} style={keptRow}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={ellipsis}>{it.name}</div>
                    <div style={small}>
                      {KIND_LABEL[it.kind]} · {it.source === "user" ? "you" : "starred"} · {it.tracks_present} / {it.tracks_total} · {fmtBytes(it.bytes)}
                    </div>
                  </div>
                  {it.source === "user" ? (
                    <SecondaryButton aria-label={`Remove ${it.name}`} disabled={busy}
                                     onClick={() => void remove(it)} style={smallBtn}>Remove</SecondaryButton>
                  ) : (
                    <span style={unstarHint}>Unstar in Navidrome to remove</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
        {extra}
      </div>
    </div>
  );
}

/** Admin → Storage: the music drive, the download queue and kept items,
 *  behind the web password like Accounts. */
export function StorageSection({ desktop }: { desktop: boolean }) {
  const { unlocked, expired } = useAdminSession();
  if (!unlocked) return <LockScreen expired={expired} purpose="manage storage" />;
  return (
    <StoragePanel desktop={desktop} extra={
      <Panel title="Uploads" wide><FileBrowser client={adminFilesClient} /></Panel>} />
  );
}

const page: CSSProperties = { padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 16 };
const muted: CSSProperties = { color: "var(--ink2)", margin: "4px 0" };
const small: CSSProperties = { color: "var(--ink2)", fontSize: 13 };
const list: CSSProperties = { listStyle: "none", margin: "4px 0", padding: 0 };
const ellipsis: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const keptRow: CSSProperties = {
  display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: "1px solid var(--rule)",
};
const unstarHint: CSSProperties = { ...small, maxWidth: 130, textAlign: "right", flexShrink: 0 };
const smallBtn: CSSProperties = { width: "auto", minHeight: 40, padding: "8px 14px" };
const pausedStyle: CSSProperties = { margin: "6px 0", color: "var(--ink)", fontSize: 14 };
const noticeStyle: CSSProperties = {
  padding: "8px 12px", borderRadius: 8, background: "var(--panel)", color: "var(--ink2)", fontSize: 13,
};
