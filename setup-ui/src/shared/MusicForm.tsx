import { useState, type ReactNode } from "react";
import {
  PrimaryButton, SecondaryButton, Field, ErrorText, NavRow, inputStyle,
} from "../components/ui";

/** Values handed to onTest/onSave. `password: ""` means "keep the stored
 *  one" (callers translate for APIs that expect something else). */
export type MusicValues = { url: string; username: string; password: string };
export type FormResult = { ok: boolean; error?: string };

type TestState =
  | { kind: "idle" }
  | { kind: "testing" }
  | { kind: "ok" }
  | { kind: "error"; message: string };

const UNREACHABLE = "Couldn't reach the Boombox. Try again.";

/** Navidrome / Subsonic connection form, shared by the first-run wizard and
 *  the Accounts page. Presentational: all I/O goes through onTest/onSave. */
export function MusicForm({
  initial, passwordSet, onTest, onSave, saveLabel = "Save", secondary, onBack,
  strict = false,
}: {
  initial: { url: string; username: string };
  passwordSet: boolean;
  onTest: (v: MusicValues) => Promise<FormResult>;
  onSave: (v: MusicValues) => Promise<FormResult>;
  saveLabel?: string;
  secondary?: ReactNode;
  onBack?: () => void;
  /** Accounts page: also require an http(s) URL and a password (unless one
   *  is stored). Off by default so the wizard keeps its lenient checks. */
  strict?: boolean;
}) {
  const [url, setUrl] = useState(initial.url);
  const [username, setUsername] = useState(initial.username);
  const [password, setPassword] = useState("");
  const [test, setTest] = useState<TestState>({ kind: "idle" });
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const canSubmit = strict
    ? /^https?:\/\/\S/.test(url.trim()) && username.trim() !== ""
      && (password !== "" || passwordSet)
    : url.trim() !== "" && username.trim() !== "";
  const values = (): MusicValues =>
    ({ url: url.trim(), username: username.trim(), password });

  const runTest = async () => {
    setTest({ kind: "testing" });
    try {
      const r = await onTest(values());
      setTest(r.ok
        ? { kind: "ok" }
        : { kind: "error", message: r.error ?? "Connection failed." });
    } catch {
      setTest({ kind: "error", message: "Couldn't reach the Boombox." });
    }
  };

  const save = async () => {
    setSaveError(null);
    setBusy(true);
    try {
      const r = await onSave(values());
      setBusy(false);
      if (!r.ok) setSaveError(r.error ?? "Couldn't connect to that library.");
    } catch {
      setBusy(false);
      setSaveError(UNREACHABLE);
    }
  };

  return (
    <>
      <Field label="Server URL">
        <input
          value={url}
          onChange={(e) => { setUrl(e.target.value); setTest({ kind: "idle" }); }}
          placeholder="http://<host>:4533"
          autoCapitalize="off" autoCorrect="off" spellCheck={false}
          aria-label="Server URL"
          style={inputStyle}
        />
      </Field>
      <Field label="Username">
        <input
          value={username}
          onChange={(e) => { setUsername(e.target.value); setTest({ kind: "idle" }); }}
          autoCapitalize="off" autoCorrect="off" spellCheck={false}
          aria-label="Username"
          style={inputStyle}
        />
      </Field>
      <Field label="Password">
        <input
          type="password"
          value={password}
          onChange={(e) => { setPassword(e.target.value); setTest({ kind: "idle" }); }}
          placeholder={passwordSet ? "saved — leave blank to keep" : undefined}
          aria-label="Password"
          style={inputStyle}
        />
      </Field>

      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <SecondaryButton
          onClick={runTest}
          disabled={!canSubmit || test.kind === "testing"}
          style={{ width: "auto", flexShrink: 0 }}
        >
          {test.kind === "testing" ? "Testing…" : "Test"}
        </SecondaryButton>
        {test.kind === "ok" && (
          <span style={{ color: "#5be7ff", fontSize: 14 }}>✓ Connected</span>
        )}
        {test.kind === "error" && (
          <span style={{ color: "#ff7878", fontSize: 14 }}>✗ {test.message}</span>
        )}
      </div>

      {saveError && <ErrorText>{saveError}</ErrorText>}

      <NavRow
        onBack={onBack}
        primary={
          <PrimaryButton onClick={save} disabled={busy || !canSubmit}>
            {busy ? "Saving…" : saveLabel}
          </PrimaryButton>
        }
        secondary={secondary}
      />
    </>
  );
}
