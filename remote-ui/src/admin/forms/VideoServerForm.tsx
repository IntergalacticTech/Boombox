// Copied from setup-ui/src/shared/VideoServerForm.tsx — the wizard's twin. Keep in step.
import { useState, type ReactNode } from "react";
import {
  PrimaryButton, SecondaryButton, Card, Field, ErrorText, NavRow, inputStyle,
} from "../ui";
import type { FormResult } from "./MusicForm";

/** Values handed to onTest/onSave. `api_key: ""` means "keep the stored
 *  key" (callers translate for APIs that expect something else). */
export type VideoValues = {
  mode: "builtin" | "remote"; base: string; api_key: string;
};
export type VideoTestResult = FormResult & { server_name?: string };

type TestState =
  | { kind: "idle" }
  | { kind: "testing" }
  | { kind: "ok"; name?: string }
  | { kind: "error"; message: string };

/** Video-server picker (built-in Jellyfin vs. a remote one), shared by the
 *  first-run wizard and the Accounts page. onSave may resolve with extra
 *  fields (e.g. `can_force`); the form only renders `error` — the parent
 *  owns any retry flow. */
export function VideoServerForm({
  initial, keySet, onTest, onSave, saveLabel = "Save", secondary, onBack,
}: {
  initial: { mode: "builtin" | "remote"; base: string };
  keySet: boolean;
  onTest?: (v: VideoValues) => Promise<VideoTestResult>;
  onSave: (v: VideoValues) => Promise<FormResult>;
  saveLabel?: string;
  secondary?: ReactNode;
  onBack?: () => void;
}) {
  const [mode, setMode] = useState<"builtin" | "remote">(initial.mode);
  const [base, setBase] = useState(initial.base);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<TestState>({ kind: "idle" });

  const values = (): VideoValues =>
    ({ mode, base: base.trim(), api_key: apiKey.trim() });
  const remoteInvalid = mode === "remote" && !/^https?:\/\//.test(base.trim());

  const save = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await onSave(values());
      setBusy(false);
      if (!r.ok) setError(r.error ?? "Couldn't save that video server.");
    } catch {
      setBusy(false);
      setError("Couldn't reach the Boombox. Try again.");
    }
  };

  const runTest = async () => {
    if (!onTest) return;
    setTest({ kind: "testing" });
    try {
      const r = await onTest(values());
      setTest(r.ok
        ? { kind: "ok", name: r.server_name }
        : { kind: "error", message: r.error ?? "Connection failed." });
    } catch {
      setTest({ kind: "error", message: "Couldn't reach the Boombox." });
    }
  };

  const pick = (m: "builtin" | "remote") => { setMode(m); setTest({ kind: "idle" }); };

  return (
    <>
      <Card selected={mode === "builtin"} onClick={() => pick("builtin")}>
        <div style={{ fontSize: 16, fontWeight: 700 }}>
          Use this Boombox's built-in Jellyfin
        </div>
        <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 4 }}>
          Recommended. Nothing else to configure.
        </div>
      </Card>

      <Card selected={mode === "remote"} onClick={() => pick("remote")}>
        <div style={{ fontSize: 16, fontWeight: 700 }}>Point at my own server</div>
        <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 4 }}>
          Use a Jellyfin server running elsewhere on your network.
        </div>
      </Card>

      {mode === "remote" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Base URL">
            <input
              value={base}
              onChange={(e) => { setBase(e.target.value); setTest({ kind: "idle" }); }}
              placeholder="http://host:8096"
              autoCapitalize="off" autoCorrect="off" spellCheck={false}
              aria-label="Base URL"
              style={inputStyle}
            />
          </Field>
          <Field label="API key (optional)">
            <input
              value={apiKey}
              onChange={(e) => { setApiKey(e.target.value); setTest({ kind: "idle" }); }}
              placeholder={keySet ? "saved — leave blank to keep" : undefined}
              autoCapitalize="off" autoCorrect="off" spellCheck={false}
              aria-label="API key"
              style={inputStyle}
            />
          </Field>
        </div>
      )}

      {onTest && (
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <SecondaryButton
            onClick={runTest}
            disabled={remoteInvalid || test.kind === "testing"}
            style={{ width: "auto", flexShrink: 0 }}
          >
            {test.kind === "testing" ? "Testing…" : "Test"}
          </SecondaryButton>
          {test.kind === "ok" && (
            <span style={{ color: "#5be7ff", fontSize: 14 }}>
              {test.name ? `Connected to ${test.name} ✓` : "Connected ✓"}
            </span>
          )}
          {test.kind === "error" && (
            <span style={{ color: "#ff7878", fontSize: 14 }}>✗ {test.message}</span>
          )}
        </div>
      )}

      {error && <ErrorText>{error}</ErrorText>}

      <NavRow
        onBack={onBack}
        primary={
          <PrimaryButton onClick={save} disabled={busy || remoteInvalid}>
            {busy ? "Saving…" : saveLabel}
          </PrimaryButton>
        }
        secondary={secondary}
      />
    </>
  );
}
