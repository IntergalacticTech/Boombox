import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { ErrorText, SecondaryButton } from "./ui";
import { LockScreen } from "./LockScreen";
import { lock, useAdminSession } from "./session";
import { UNREACHABLE, ACCOUNTS_DESKTOP_COLUMNS } from "./AccountsSection";
import { adminFilesClient, storageApi } from "./storage/api";
import type { Downloads, KeptItem, KeptSource, PauseReason, StorageOverview } from "./storage/types";
import { SectionMessage } from "../components/SectionMessage";
import { FileBrowser } from "../screens/Files";

/** Overview poll while downloads run or wait; STORAGE_IDLE_POLL_MS otherwise
 *  (the overview costs the library a query per kept item). */
export const STORAGE_POLL_MS = 5000;
export const STORAGE_IDLE_POLL_MS = 15000;
export const PAUSED_TEXT: Record<PauseReason, string> = {
  streaming: "Paused while music streams from the Home Library.",
  hot: "Paused — the boombox is hot (70 °C or more); checking again every minute.",
  offline: "Paused — the Home Library server can't be reached.",
  low_space: "Stopped — free space is below the reserve.",
};
const KIND_LABEL: Record<KeptItem["kind"], string> = {
  album: "Album", artist: "Artist", playlist: "Playlist", starred_tracks: "Songs", card_tracks: "Songs",
};
const SOURCE_LABEL: Record<KeptSource, string> = { user: "you", starred: "starred", card: "card" };
/** Why a non-user item has no Remove button. */
const KEEP_HINT: Record<Exclude<KeptSource, "user">, string> = {
  starred: "Unstar in Navidrome to remove",
  card: "On an RFID card — unbind the card to remove",
};

function downloading(d: Downloads): boolean {
  return d.in_flight.length > 0 || d.queued > 0;
}

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
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  // Every request gets a sequence number; an answer is applied only if no
  // later request has already been answered, so a slow poll can't overwrite
  // a newer overview (e.g. the refresh after Remove) and never blocks polls.
  const sent = useRef(0);
  const applied = useRef(0);
  const sinceLast = useRef(0);
  const active = useRef(true);

  const refresh = useCallback(async () => {
    const seq = ++sent.current;
    sinceLast.current = 0;
    const apply = (fn: () => void) => {
      if (seq < applied.current) return;
      applied.current = seq;
      fn();
    };
    try {
      const r = await storageApi.overview();
      if ("drive" in r) {
        apply(() => { setData(r); setError(null); active.current = downloading(r.downloads); });
      } else {
        apply(() => setError(r.error || UNREACHABLE));
      }
    } catch {
      apply(() => setError(UNREACHABLE));
    }
  }, []);

  // Polls only while mounted, and this panel is mounted only while unlocked
  // (a 401 clears the session → StorageSection swaps in the lock screen →
  // this effect's cleanup stops the timer). Every STORAGE_POLL_MS while
  // downloads run or are queued, else every STORAGE_IDLE_POLL_MS; skipped
  // while the tab is in the background.
  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => {
      sinceLast.current += STORAGE_POLL_MS;
      if (document.hidden) return;
      if (sinceLast.current < (active.current ? STORAGE_POLL_MS : STORAGE_IDLE_POLL_MS)) return;
      void refresh();
    }, STORAGE_POLL_MS);
    return () => window.clearInterval(t);
  }, [refresh, attempt]);

  const remove = async (item: KeptItem) => {
    if (!window.confirm(`Remove ${item.name} from the boombox? Its downloaded songs are deleted (songs another kept item needs stay).`)) return;
    setBusy(true);
    try {
      const r = await storageApi.remove(item.kind, item.id);
      setNotice(r.ok ? { text: `Removed ${item.name} — ${fmtBytes(r.freed_bytes)} freed.`, error: false }
                     : { text: r.error || "Couldn't remove it.", error: true });
    } catch {
      setNotice({ text: UNREACHABLE, error: true });
    }
    setBusy(false);
    void refresh();
  };

  const retry = async () => {
    setBusy(true);
    try {
      const r = await storageApi.retry();
      setNotice(r.ok ? { text: `Retrying ${r.retried} download${r.retried === 1 ? "" : "s"}.`, error: false }
                     : { text: r.error || "Couldn't retry.", error: true });
    } catch {
      setNotice({ text: UNREACHABLE, error: true });
    }
    setBusy(false);
    void refresh();
  };

  // The grid is always there so the Uploads panel (extra) keeps its place —
  // and any upload in progress — while the overview loads, fails or recovers;
  // uploads don't need the library.
  return (
    <div style={page}>
      <Header />
      {!data && (error
        ? <SectionMessage message={error} onRetry={() => setAttempt((n) => n + 1)} />
        : <p style={muted}>Loading…</p>)}
      {data && error && <ErrorText>{error}</ErrorText>}
      {notice && (notice.error ? <ErrorText>{notice.text}</ErrorText>
                               : <div role="status" style={noticeStyle}>{notice.text}</div>)}
      <div data-testid="storage-grid" style={{
        display: "grid", gap: 16, alignItems: "start",
        gridTemplateColumns: desktop ? ACCOUNTS_DESKTOP_COLUMNS : "minmax(0, 1fr)",
      }}>
        {data && <Overview data={data} busy={busy} onRemove={(it) => void remove(it)}
                           onRetry={() => void retry()} />}
        {extra}
      </div>
    </div>
  );
}

function Overview({ data, busy, onRemove, onRetry }: {
  data: StorageOverview; busy: boolean; onRemove: (it: KeptItem) => void; onRetry: () => void;
}) {
  const { drive, downloads, kept } = data;
  const low = drive.present && drive.free_bytes != null && drive.free_bytes < drive.reserve_bytes;
  return (
    <>
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
                           onClick={onRetry} style={smallBtn}>Retry failed</SecondaryButton>
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
                    {KIND_LABEL[it.kind]} · {SOURCE_LABEL[it.source]} · {it.tracks_present} / {it.tracks_total} · {fmtBytes(it.bytes)}
                  </div>
                </div>
                {it.source === "user" ? (
                  <SecondaryButton aria-label={`Remove ${it.name}`} disabled={busy}
                                   onClick={() => onRemove(it)} style={smallBtn}>Remove</SecondaryButton>
                ) : (
                  <span style={keepHint}>{KEEP_HINT[it.source]}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
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
const keepHint: CSSProperties = { ...small, maxWidth: 130, textAlign: "right", flexShrink: 0 };
const smallBtn: CSSProperties = { width: "auto", minHeight: 40, padding: "8px 14px" };
const pausedStyle: CSSProperties = { margin: "6px 0", color: "var(--ink)", fontSize: 14 };
const noticeStyle: CSSProperties = {
  padding: "8px 12px", borderRadius: 8, background: "var(--panel)", color: "var(--ink2)", fontSize: 13,
};
