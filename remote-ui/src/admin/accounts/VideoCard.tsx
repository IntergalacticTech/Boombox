import { useCallback, useEffect, useState } from "react";
import { accountsApi } from "./api";
import type { VideoInfo, JfUser, OkResult } from "./types";
import { VideoServerForm, type VideoValues, type VideoTestResult } from "../forms/VideoServerForm";
import { ErrorText, SecondaryButton } from "../ui";

const BUILTIN_BASE = "http://127.0.0.1:8096";
type SaveResult = OkResult & { can_force?: boolean };

export function VideoCard({ onChanged }: { onChanged: () => void }) {
  const [info, setInfo] = useState<VideoInfo | null>(null);
  const [users, setUsers] = useState<JfUser[]>([]);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  // Values of the last save the server refused only because it couldn't
  // reach the server — offered back as "Save anyway".
  const [forceable, setForceable] = useState<VideoValues | null>(null);
  const [forceError, setForceError] = useState<string | null>(null);

  const loadUsers = useCallback(() => {
    setUsers([]); setUsersError(null);
    accountsApi.get<{ users?: JfUser[]; error?: string }>("video/users")
      .then((u) => { setUsers(u.users ?? []); setUsersError(u.error ?? null); })
      .catch(() => setUsersError("Couldn't load Jellyfin users."));
  }, []);

  const load = useCallback(() => accountsApi.get<VideoInfo>("video").then((v) => {
    if (!v || typeof v.key_set !== "boolean") {
      setMsg((v as { error?: string })?.error ?? "Couldn't load the video settings.");
      return;
    }
    setInfo(v);
    setVersion((n) => n + 1);
    if (v.mode === "remote" && v.key_set && !v.kiosk_user) loadUsers();
    else { setUsers([]); setUsersError(null); }
  }).catch(() => setMsg("Couldn't reach the Boombox.")), [loadUsers]);
  useEffect(() => { void load(); }, [load]);

  if (!info) return msg ? <ErrorText>{msg}</ErrorText> : <p>Loading…</p>;

  const saved = () => { setForceable(null); setForceError(null); onChanged(); void load(); };

  const save = async (v: VideoValues): Promise<SaveResult> => {
    setForceable(null); setForceError(null);
    const r = await accountsApi.put<SaveResult>("video", v);
    if (r.ok) saved();
    else if (r.can_force === true) setForceable(v);
    return r;
  };

  const saveAnyway = async () => {
    if (!forceable) return;
    setBusy(true); setForceError(null);
    try {
      const r = await accountsApi.put<SaveResult>("video", { ...forceable, force: true });
      if (r.ok) saved(); else setForceError(r.error ?? "Couldn't save that video server.");
    } catch {
      setForceError("Couldn't reach the Boombox. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const signIn = async (u: JfUser) => {
    setBusy(true); setMsg(null);
    try {
      const r = await accountsApi.post<OkResult & { user?: string }>(
        "video/kiosk-signin", { user_id: u.id });
      if (r.ok) { setInfo({ ...info, kiosk_user: r.user ?? u.name }); onChanged(); }
      else setMsg(r.error ?? "Sign-in failed.");
    } catch {
      setMsg("Couldn't reach the Boombox.");
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await accountsApi.post<OkResult>("video/kiosk-signout", {});
      if (r.ok) { setInfo({ ...info, kiosk_user: null }); onChanged(); loadUsers(); }
      else setMsg(r.error ?? "Sign-out failed.");
    } catch {
      setMsg("Couldn't reach the Boombox.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <VideoServerForm key={version}
        initial={{ mode: info.mode, base: info.mode === "remote" ? info.base : "" }}
        keySet={info.key_set}
        onTest={(v: VideoValues) => accountsApi.post<VideoTestResult>("video/test",
          { base: v.mode === "builtin" ? BUILTIN_BASE : v.base, api_key: v.api_key })}
        onSave={save}
        secondary={forceable ? (
          <SecondaryButton onClick={saveAnyway} disabled={busy}>Save anyway</SecondaryButton>
        ) : undefined} />
      {forceError && <ErrorText>{forceError}</ErrorText>}
      {/* Remote only: the built-in server needs no picker (the kiosk opens it
          at localhost, and the phone remote finds its session itself). */}
      {info.mode === "remote" && info.key_set && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h3 style={{ fontSize: 15, margin: 0 }}>Kiosk sign-in</h3>
          {info.kiosk_user ? (
            <>
              <p style={{ margin: 0 }}>Kiosk signed in as {info.kiosk_user}</p>
              <SecondaryButton onClick={signOut} disabled={busy}>Sign out</SecondaryButton>
            </>
          ) : (
            <>
              <p style={{ margin: 0, fontSize: 13, color: "var(--ink2)" }}>
                Pick the Jellyfin user the TV screen should browse as.</p>
              {users.map((u) => (
                <SecondaryButton key={u.id} onClick={() => signIn(u)} disabled={busy}>
                  Sign kiosk in as {u.name}
                </SecondaryButton>
              ))}
              {usersError && <ErrorText>{usersError}</ErrorText>}
            </>
          )}
          {msg && <ErrorText>{msg}</ErrorText>}
        </div>
      )}
    </div>
  );
}
