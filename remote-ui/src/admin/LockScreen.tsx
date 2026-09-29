import { useState, type FormEvent } from "react";
import { ErrorText, Field, PrimaryButton, inputStyle } from "./ui";
import { unlock } from "./session";

/** Admin sections stay locked until the boombox web password is entered. */
export function LockScreen({ expired }: { expired: boolean }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await unlock(password);
    setBusy(false);
    if (r.ok) setPassword("");
    else setError(r.error);
  };

  return (
    <form onSubmit={submit} style={{
      padding: 24, maxWidth: 420, margin: "0 auto",
      display: "flex", flexDirection: "column", gap: 14,
    }}>
      <h1 style={{ fontSize: 22, margin: 0 }}>🔒 Admin</h1>
      <p style={{ margin: 0, color: "var(--ink2)", fontSize: 14 }}>
        {expired
          ? "Your admin session expired. Enter the boombox web password again."
          : "Enter the boombox web password to manage accounts."}
      </p>
      <Field label="Web password">
        <input type="password" autoComplete="current-password" value={password}
               onChange={(e) => setPassword(e.target.value)} aria-label="Web password"
               style={inputStyle} />
      </Field>
      {error && <ErrorText>{error}</ErrorText>}
      <PrimaryButton type="submit" disabled={busy || password === ""}>
        {busy ? "Unlocking…" : "Unlock"}
      </PrimaryButton>
    </form>
  );
}
