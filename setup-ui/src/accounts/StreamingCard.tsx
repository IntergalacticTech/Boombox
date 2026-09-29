import { useCallback, useEffect, useState } from "react";
import { accountsApi } from "./api";
import type { OkResult, Receiver, StreamingInfo } from "./types";
import { ErrorText, Field, PrimaryButton, inputStyle } from "../components/ui";

type SaveFn = (body: Record<string, unknown>) => Promise<OkResult>;

function useSave(save: SaveFn) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (body: Record<string, unknown>) => {
    setBusy(true); setError(null);
    try {
      const r = await save(body);
      if (!r.ok) setError(r.error ?? "Couldn't save.");
    } catch {
      setError("Couldn't reach the Boombox. Try again.");
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

function RunState({ r }: { r: Receiver }) {
  return <span style={{ fontSize: 12, color: "var(--ink2)" }}>
    {r.active ? "running" : "stopped"}</span>;
}

function AirPlayRow({ r, save }: { r: Receiver; save: SaveFn }) {
  const [name, setName] = useState(r.name);
  const [password, setPassword] = useState("");
  const [clear, setClear] = useState(false);
  const { busy, error, run } = useSave(save);
  if (!r.installed) return <p style={{ margin: 0 }}>AirPlay — not installed</p>;

  const body: Record<string, unknown> = {};
  if (name.trim() !== r.name) body.airplay_name = name.trim();
  if (clear) body.airplay_password_clear = true;
  else if (password !== "") body.airplay_password = password;
  const empty = Object.keys(body).length === 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <strong>AirPlay</strong><RunState r={r} />
      </div>
      <Field label="AirPlay name">
        <input value={name} onChange={(e) => setName(e.target.value)}
          aria-label="AirPlay name" style={inputStyle} />
      </Field>
      <Field label="AirPlay password (optional)">
        <input type="password" value={password} disabled={clear}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={r.password_set ? "saved — leave blank to keep" : "none"}
          aria-label="AirPlay password" style={inputStyle} />
      </Field>
      {r.password_set && (
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 14 }}>
          <input type="checkbox" checked={clear}
            onChange={(e) => setClear(e.target.checked)} />
          Remove password
        </label>
      )}
      {error && <ErrorText>{error}</ErrorText>}
      <PrimaryButton onClick={() => run(body)} disabled={busy || empty}>
        {busy ? "Saving…" : "Save AirPlay"}
      </PrimaryButton>
    </div>
  );
}

function SpotifyRow({ r, save }: { r: Receiver; save: SaveFn }) {
  const [name, setName] = useState(r.name);
  const { busy, error, run } = useSave(save);
  if (!r.installed) return <p style={{ margin: 0 }}>Spotify Connect — not installed</p>;
  const changed = name.trim() !== r.name && name.trim() !== "";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <strong>Spotify Connect</strong><RunState r={r} />
      </div>
      <Field label="Spotify name">
        <input value={name} onChange={(e) => setName(e.target.value)}
          aria-label="Spotify name" style={inputStyle} />
      </Field>
      {error && <ErrorText>{error}</ErrorText>}
      <PrimaryButton onClick={() => run({ spotify_name: name.trim() })}
        disabled={busy || !changed}>
        {busy ? "Saving…" : "Save Spotify"}
      </PrimaryButton>
    </div>
  );
}

export function StreamingCard({ onChanged }: { onChanged: () => void }) {
  const [info, setInfo] = useState<StreamingInfo | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  // GET returns 502 {"error": …} when the root helper fails — show it as a
  // problem, never crash on the missing receiver objects.
  const load = useCallback(() => accountsApi.get<StreamingInfo & { error?: string }>("streaming")
    .then((s) => {
      if (s && s.airplay && s.spotify) { setInfo(s); setProblem(null); setVersion((v) => v + 1); }
      else setProblem(s?.error ?? "Receiver status unavailable.");
    }).catch(() => setProblem("Couldn't reach the Boombox.")), []);
  useEffect(() => { void load(); }, [load]);

  const save: SaveFn = async (body) => {
    const r = await accountsApi.put<OkResult>("streaming", body);
    if (r.ok) { onChanged(); void load(); }
    return r;
  };

  if (!info) return problem ? <ErrorText>Problem: {problem}</ErrorText> : <p>Loading…</p>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {problem && <ErrorText>Problem: {problem}</ErrorText>}
      <AirPlayRow key={`a${version}`} r={info.airplay} save={save} />
      <SpotifyRow key={`s${version}`} r={info.spotify} save={save} />
    </div>
  );
}
