import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useApi, ApiError, apiErrorMessage } from "../lib/api";
import type { Navigate } from "../lib/route";
import { SkeletonRows } from "../components/Skeleton";
import { SectionMessage } from "../components/SectionMessage";

export interface Entry {
  name: string; kind: "dir" | "file"; size?: number; mtime?: number; tracks?: number; deletable?: boolean;
}
export interface BrowseResult { path: string; parent: string | null; entries: Entry[] }

/** Where a FileBrowser reads and writes. Household: browse (+ rescan) via
 *  the pair token. Admin → Storage: browse, upload, delete via the admin
 *  session. Controls appear only for what the client can do. */
export interface FilesClient {
  browse(path: string): Promise<BrowseResult>;
  upload?(files: File[]): Promise<{ saved: string[] }>;
  remove?(path: string): Promise<unknown>;
  rescan?(): Promise<unknown>;
}

export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function errorText(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return apiErrorMessage(e, fallback);
  if (e instanceof TypeError) return "Couldn't reach the boombox.";
  return e instanceof Error && e.message ? e.message : fallback;
}

/** The music folder (hidden files filtered server-side except the .usb
 *  mount link). Uploads land in uploads/ and trigger a library scan. */
export function FileBrowser({ client }: { client: FilesClient }) {
  const [path, setPath] = useState("");
  const [data, setData] = useState<BrowseResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reload = (p = path) => {
    setBusy(true);
    setErr(null);
    client.browse(p)
      .then((r) => { setData(r); setPath(r.path); })
      .catch((e: unknown) => setErr(errorText(e, "Couldn't list the files")))
      .finally(() => setBusy(false));
  };

  useEffect(() => { reload(""); /* mount-only */ }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const enterDir = (name: string) => reload(path ? `${path}/${name}` : name);
  const upDir = () => {
    if (data?.parent === null && path === "") return;
    reload(data?.parent ?? "");
  };

  const onUpload = async (files: FileList | null) => {
    if (!client.upload || !files || files.length === 0 || uploading) return;
    setUploading(true);
    setStatus(`Uploading ${files.length} file(s)…`);
    try {
      const res = await client.upload(Array.from(files));
      setStatus(`Uploaded: ${res.saved.length} file(s)`);
      reload();
    } catch (e: unknown) {
      setStatus(errorText(e, "Upload failed"));
    } finally {
      setUploading(false);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const onDelete = async (name: string) => {
    if (!client.remove || !window.confirm(`Delete ${name}?`)) return;
    try {
      await client.remove(path ? `${path}/${name}` : name);
      reload();
    } catch (e: unknown) {
      setStatus(errorText(e, "Delete failed"));
    }
  };

  const onRescan = async () => {
    if (!client.rescan) return;
    setStatus("Rescanning library…");
    try {
      await client.rescan();
      setStatus("Library rescan started (can take a few minutes).");
    } catch (e: unknown) {
      setStatus(errorText(e, "Rescan failed"));
    }
  };

  return (
    <div>
      <header style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <button type="button" onClick={upDir} disabled={path === "" && data?.parent === null}
                aria-label="Up" style={iconBtn}>‹</button>
        <div style={{ fontFamily: "var(--mono)", fontSize: 13, color: "var(--ink2)", flex: 1,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          /{path || ""}
        </div>
        {client.rescan && (
          <button type="button" onClick={() => void onRescan()} style={smallBtn}
                  aria-label="Rescan library">↻</button>
        )}
        {client.upload && (
          <>
            <button type="button" onClick={() => fileInputRef.current?.click()} disabled={uploading}
                    style={{ ...primaryBtn, opacity: uploading ? 0.5 : 1 }}>
              + Upload</button>
            <input ref={fileInputRef} type="file" multiple style={{ display: "none" }}
                   aria-label="Choose files to upload" onChange={(e) => void onUpload(e.target.files)} />
          </>
        )}
      </header>
      {status && <div role="status" style={statusStyle}>{status}</div>}
      {err ? (
        <SectionMessage message={err} onRetry={() => reload()} />
      ) : (
        <>
          {busy && !data && <SkeletonRows count={8} />}
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {data?.entries.map((e) => (
              <li key={e.name} style={{ display: "flex", alignItems: "center", gap: 12,
                                        padding: "10px 4px", borderBottom: "1px solid var(--rule)" }}>
                {e.kind === "dir" ? (
                  <button type="button" onClick={() => enterDir(e.name)}
                          style={{ ...rowBtn, textAlign: "left", flex: 1 }}>
                    <span style={{ marginRight: 8 }}>📁</span>{e.name}
                    {typeof e.tracks === "number" && e.tracks > 0 && (
                      <span style={{ marginLeft: 8, color: "var(--ink2)", fontSize: 12 }}>({e.tracks})</span>
                    )}
                  </button>
                ) : (
                  <>
                    <span style={{ flex: 1 }}>
                      <span style={{ marginRight: 8 }}>🎵</span>{e.name}
                      {typeof e.size === "number" && (
                        <span style={{ marginLeft: 8, color: "var(--ink2)", fontSize: 12 }}>{fmtSize(e.size)}</span>
                      )}
                    </span>
                    {client.remove && e.deletable && (
                      <button type="button" onClick={() => void onDelete(e.name)}
                              aria-label={`Delete ${e.name}`} style={iconBtn}>×</button>
                    )}
                  </>
                )}
              </li>
            ))}
            {data && data.entries.length === 0 && (
              <li style={{ padding: "16px 4px", color: "var(--ink2)" }}>Empty directory.</li>
            )}
          </ul>
        </>
      )}
    </div>
  );
}

/** Household Files tab: browse only. Uploading and deleting live in
 *  Admin → Storage (the server refuses them on the pair-token tier). */
export function Files({ navigate }: { navigate: Navigate }) {
  const api = useApi();
  const client = useMemo<FilesClient>(() => ({
    browse: (p) => api.get<BrowseResult>(`api/remote/files/browse?path=${encodeURIComponent(p)}`),
    rescan: () => api.post<{ ok: boolean }>("api/remote/library/rescan"),
  }), [api]);
  return (
    <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
      <div role="note" style={pointer}>
        <span style={{ flex: 1, minWidth: 0 }}>Uploading and deleting files moved to Admin → Storage.</span>
        <button type="button" onClick={() => navigate("storage")} style={smallBtn}>Open Storage</button>
      </div>
      <FileBrowser client={client} />
    </div>
  );
}

const iconBtn: CSSProperties = {
  width: 36, height: 36, borderRadius: 18, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", cursor: "pointer", fontSize: 18,
};
const primaryBtn: CSSProperties = {
  padding: "8px 14px", borderRadius: 8, border: 0, background: "var(--accent)",
  color: "var(--bg)", fontSize: 14, fontWeight: 600, cursor: "pointer",
};
const rowBtn: CSSProperties = {
  background: "transparent", border: 0, color: "var(--ink)", fontSize: 15, padding: "4px 0", cursor: "pointer",
};
const smallBtn: CSSProperties = {
  padding: "6px 10px", borderRadius: 6, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 13, cursor: "pointer", flexShrink: 0,
};
const statusStyle: CSSProperties = {
  padding: "8px 12px", marginBottom: 12, borderRadius: 8, background: "var(--panel)",
  color: "var(--ink2)", fontSize: 13,
};
const pointer: CSSProperties = {
  display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", padding: "10px 12px",
  borderRadius: 10, background: "var(--panel)", color: "var(--ink2)", fontSize: 14,
};
