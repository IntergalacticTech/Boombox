import { useCallback, useEffect, useState } from "react";
import { ErrorText } from "../ui";
import { accountsApi } from "./api";
import type { MusicInfo, OkResult } from "./types";
import { MusicForm, type MusicValues } from "../forms/MusicForm";

export function MusicCard({ onChanged }: { onChanged: () => void }) {
  const [info, setInfo] = useState<MusicInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Bumped after each successful save so MusicForm (which reads `initial`
  // once) remounts showing the saved state.
  const [version, setVersion] = useState(0);

  const load = useCallback(() => accountsApi.get<MusicInfo>("music").then((m) => {
    if (m && typeof m.url === "string") { setInfo(m); setLoadError(null); setVersion((v) => v + 1); }
    else setLoadError((m as { error?: string })?.error ?? "Couldn't load the music settings.");
  }).catch(() => setLoadError("Couldn't reach the Boombox.")), []);
  useEffect(() => { void load(); }, [load]);

  if (!info) return loadError ? <ErrorText>{loadError}</ErrorText> : <p>Loading…</p>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {info.last_sync_ts ? <p style={{ fontSize: 13, margin: 0, color: "var(--ink2)" }}>
        Last sync {new Date(info.last_sync_ts * 1000).toLocaleString()}{info.syncing ? " (syncing…)" : ""}</p>
        : info.syncing ? <p style={{ fontSize: 13, margin: 0, color: "var(--ink2)" }}>Syncing…</p> : null}
      {info.prune_deferred != null && <p style={{ fontSize: 13, margin: 0, color: "#fbbf24" }}>
        The server listed far fewer albums than before — removal is on hold until it's confirmed.</p>}
      {loadError && <ErrorText>{loadError}</ErrorText>}
      <MusicForm key={version} strict initial={info} passwordSet={info.configured}
        onTest={(v: MusicValues) => accountsApi.post<OkResult>("music/test", v)}
        onSave={async (v: MusicValues) => {
          const r = await accountsApi.put<OkResult>("music", v);
          if (r.ok) { onChanged(); void load(); }
          return r;
        }} />
      <p style={{ fontSize: 12, margin: 0, opacity: 0.7 }}>
        Tip: use a dedicated, non-admin Navidrome user for this boombox.</p>
    </div>
  );
}
