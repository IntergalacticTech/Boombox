import { useEffect, useRef, useState } from "react";
import { useApi, ApiError } from "../lib/api";

interface Entry {
  name: string;
  kind: "dir" | "file";
  size?: number;
  mtime?: number;
  tracks?: number;
  deletable?: boolean;
}

interface BrowseResult {
  path: string;
  parent: string | null;
  entries: Entry[];
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

/** Music library file browser + uploader. Mirrors the music_root directory
 *  tree, with hidden files filtered server-side except the .usb mount link.
 *  Uploads land in <root>/uploads/ and trigger a Mopidy library scan. */
export function Files() {
  const api = useApi();
  const [path, setPath] = useState("");
  const [data, setData] = useState<BrowseResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reload = (p = path) => {
    setBusy(true);
    setErr(null);
    api
      .get<BrowseResult>(
        `api/remote/files/browse?path=${encodeURIComponent(p)}`,
      )
      .then((r) => { setData(r); setPath(r.path); })
      .catch((e: unknown) =>
        setErr(e instanceof ApiError ? `${e.status}` : "failed"))
      .finally(() => setBusy(false));
  };

  useEffect(() => { reload(""); /* mount-only */ }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const enterDir = (name: string) => {
    const next = path ? `${path}/${name}` : name;
    reload(next);
  };

  const upDir = () => {
    if (data?.parent === null && path === "") return;
    reload(data?.parent ?? "");
  };

  const onUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadStatus(`Uploading ${files.length} file(s)…`);
    try {
      const res = await api.uploadFiles<{ saved: string[] }>(
        "api/remote/files/upload", Array.from(files),
      );
      setUploadStatus(`Uploaded: ${res.saved.length} file(s)`);
      reload();
    } catch (e: unknown) {
      setUploadStatus(
        e instanceof ApiError ? `Upload failed (${e.status})` : "Upload failed",
      );
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const onDelete = async (name: string) => {
    if (!window.confirm(`Delete ${name}?`)) return;
    const rel = path ? `${path}/${name}` : name;
    try {
      await api.post<{ deleted: string }>("api/remote/files/delete",
                                          { path: rel });
      reload();
    } catch (e: unknown) {
      setErr(e instanceof ApiError ? `delete failed (${e.status})` : "delete failed");
    }
  };

  return (
    <div style={{ padding: 16, paddingBottom: 96 }}>
      <header style={{ display: "flex", alignItems: "center", gap: 12,
                       marginBottom: 12 }}>
        <button type="button" onClick={upDir}
                disabled={path === "" && data?.parent === null}
                aria-label="Up"
                style={iconBtn}>‹</button>
        <div style={{ fontFamily: "var(--mono)", fontSize: 13,
                      color: "var(--ink2)", flex: 1,
                      overflow: "hidden", textOverflow: "ellipsis",
                      whiteSpace: "nowrap" }}>
          /{path || ""}
        </div>
        <button type="button"
                onClick={() => fileInputRef.current?.click()}
                style={primaryBtn}>+ Upload</button>
        <input ref={fileInputRef} type="file" multiple
               style={{ display: "none" }}
               aria-label="Choose files to upload"
               onChange={(e) => onUpload(e.target.files)} />
      </header>

      {uploadStatus && (
        <div role="status" style={{
          padding: "8px 12px", marginBottom: 12, borderRadius: 8,
          background: "var(--panel)", color: "var(--ink2)", fontSize: 13,
        }}>{uploadStatus}</div>
      )}
      {err && (
        <div role="alert" style={{
          padding: "8px 12px", marginBottom: 12, borderRadius: 8,
          background: "var(--panel)", color: "var(--accent2)", fontSize: 13,
        }}>Error: {err}</div>
      )}

      {busy && !data && <div style={{ color: "var(--ink2)" }}>Loading…</div>}

      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {data?.entries.map((e) => (
          <li key={e.name} style={{
            display: "flex", alignItems: "center", gap: 12,
            padding: "10px 4px", borderBottom: "1px solid var(--rule)",
          }}>
            {e.kind === "dir" ? (
              <button type="button" onClick={() => enterDir(e.name)}
                      style={{ ...rowBtn, textAlign: "left", flex: 1 }}>
                <span style={{ marginRight: 8 }}>📁</span>
                {e.name}
                {typeof e.tracks === "number" && e.tracks > 0 && (
                  <span style={{ marginLeft: 8, color: "var(--ink2)",
                                 fontSize: 12 }}>({e.tracks})</span>
                )}
              </button>
            ) : (
              <>
                <span style={{ flex: 1 }}>
                  <span style={{ marginRight: 8 }}>🎵</span>{e.name}
                  {typeof e.size === "number" && (
                    <span style={{ marginLeft: 8, color: "var(--ink2)",
                                   fontSize: 12 }}>{fmtSize(e.size)}</span>
                  )}
                </span>
                {e.deletable && (
                  <button type="button"
                          onClick={() => onDelete(e.name)}
                          aria-label={`Delete ${e.name}`}
                          style={iconBtn}>×</button>
                )}
              </>
            )}
          </li>
        ))}
        {data && data.entries.length === 0 && (
          <li style={{ padding: "16px 4px", color: "var(--ink2)" }}>
            Empty directory.
          </li>
        )}
      </ul>
    </div>
  );
}

const iconBtn: React.CSSProperties = {
  width: 36, height: 36, borderRadius: 18,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", cursor: "pointer", fontSize: 18,
};
const primaryBtn: React.CSSProperties = {
  padding: "8px 14px", borderRadius: 8, border: 0,
  background: "var(--accent)", color: "var(--bg)",
  fontSize: 14, fontWeight: 600, cursor: "pointer",
};
const rowBtn: React.CSSProperties = {
  background: "transparent", border: 0, color: "var(--ink)",
  fontSize: 15, padding: "4px 0", cursor: "pointer",
};
