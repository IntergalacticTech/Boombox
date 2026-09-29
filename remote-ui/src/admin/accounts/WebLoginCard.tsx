import { useState } from "react";
import { accountsApi } from "./api";
import type { OkResult } from "./types";
import { ErrorText, Field, PrimaryButton, inputStyle } from "../ui";

const MIN = 10;
const MAX = 128;

export function WebLoginCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const tooShort = next.length > 0 && next.length < MIN;
  const mismatch = repeat.length > 0 && next !== repeat;
  const valid = current !== "" && next.length >= MIN && next.length <= MAX && next === repeat;

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const r = await accountsApi.put<OkResult>("web-login",
        { current_password: current, new_password: next });
      if (r.ok) {
        // The admin session survives a password change; no reload needed.
        setDone(true);
      } else {
        setError(r.error ?? "Couldn't change the password.");
      }
    } catch {
      setError("Couldn't reach the Boombox. Try again.");
    } finally {
      setBusy(false);
    }
  };

  if (done) return <p style={{ margin: 0 }}>
    Password changed — use the new one next time you unlock Admin or open the music share.</p>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <p style={{ margin: 0, fontSize: 13, color: "var(--ink2)" }}>
        The boombox web password (user <code>boombox</code>): it unlocks Admin here and the music file share.</p>
      <Field label="Current password">
        <input type="password" value={current} autoComplete="current-password"
          onChange={(e) => setCurrent(e.target.value)} style={inputStyle} />
      </Field>
      <Field label="New password">
        <input type="password" value={next} autoComplete="new-password" maxLength={MAX}
          onChange={(e) => setNext(e.target.value)} style={inputStyle} />
      </Field>
      <Field label="Repeat new password">
        <input type="password" value={repeat} autoComplete="new-password" maxLength={MAX}
          onChange={(e) => setRepeat(e.target.value)} style={inputStyle} />
      </Field>
      {tooShort && <span style={{ fontSize: 13, color: "#fbbf24" }}>
        At least {MIN} characters.</span>}
      {mismatch && <span style={{ fontSize: 13, color: "#fbbf24" }}>
        The new passwords don't match.</span>}
      {error && <ErrorText>{error}</ErrorText>}
      <PrimaryButton onClick={submit} disabled={busy || !valid}>
        {busy ? "Changing…" : "Change password"}
      </PrimaryButton>
    </div>
  );
}
