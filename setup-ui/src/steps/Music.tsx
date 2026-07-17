import { useState } from "react";
import type { WizardCtx } from "../App";
import type { MusicTestResult, OkResult } from "../lib/types";
import {
  PrimaryButton, SecondaryButton, Field, ErrorText, StepBody, NavRow,
  inputStyle,
} from "../components/ui";

type TestState =
  | { kind: "idle" }
  | { kind: "testing" }
  | { kind: "ok" }
  | { kind: "error"; message: string };

/** Step 4 — connect a Navidrome / Subsonic music library. */
export function Music({ ctx }: { ctx: WizardCtx }) {
  const { api, status, update, next, back } = ctx;
  const [url, setUrl] = useState(status.music.url);
  const [username, setUsername] = useState(status.music.username);
  const [password, setPassword] = useState("");
  const [test, setTest] = useState<TestState>({ kind: "idle" });
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const canSubmit = url.trim() !== "" && username.trim() !== "";

  const runTest = async () => {
    setTest({ kind: "testing" });
    try {
      const r = await api.post<MusicTestResult>("music/test", {
        url: url.trim(), username: username.trim(), password,
      });
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
      // The server re-tests the connection before saving; a 400 means the
      // URL/credentials failed — do not advance.
      const r = await api.put<OkResult>("music", {
        url: url.trim(), username: username.trim(), password,
      });
      setBusy(false);
      if (!r.ok) {
        setSaveError(r.error ?? "Couldn't connect to that library.");
        return;
      }
      update({ musicConfigured: true });
      next();
    } catch {
      setBusy(false);
      setSaveError("Couldn't reach the Boombox. Try again.");
    }
  };

  return (
    <StepBody
      title="Connect your music"
      subtitle="Point the Boombox at your Navidrome or Subsonic library."
    >
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
        onBack={back}
        primary={
          <PrimaryButton onClick={save} disabled={busy || !canSubmit}>
            {busy ? "Saving…" : "Save & continue"}
          </PrimaryButton>
        }
        secondary={<SecondaryButton onClick={next}>Skip for now</SecondaryButton>}
      />
    </StepBody>
  );
}
