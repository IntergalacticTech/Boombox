import { useState } from "react";
import type { WizardCtx } from "../App";
import type { VideoResult } from "../lib/types";
import {
  PrimaryButton, SecondaryButton, Card, Field, ErrorText, StepBody, NavRow,
  inputStyle,
} from "../components/ui";

/** Step 5 — pick a video server: this Boombox's built-in Jellyfin, or a
 *  remote one. */
export function Video({ ctx }: { ctx: WizardCtx }) {
  const { api, status, update, next, back } = ctx;
  const [mode, setMode] = useState<"builtin" | "remote">(status.video.mode);
  const [base, setBase] = useState(status.video.base);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    setBusy(true);
    try {
      const body = mode === "remote"
        ? { mode, base: base.trim(), api_key: apiKey.trim() || undefined }
        : { mode };
      const r = await api.put<VideoResult>("video", body);
      setBusy(false);
      if (!r.ok) {
        setError(r.error ?? "Couldn't save that video server.");
        return;
      }
      update({ videoMode: r.mode ?? mode });
      next();
    } catch {
      setBusy(false);
      setError("Couldn't reach the Boombox. Try again.");
    }
  };

  const remoteInvalid = mode === "remote" && !/^https?:\/\//.test(base.trim());

  return (
    <StepBody
      title="Choose a video server"
      subtitle="Where should the Boombox stream video from?"
    >
      <Card selected={mode === "builtin"} onClick={() => setMode("builtin")}>
        <div style={{ fontSize: 16, fontWeight: 700 }}>
          Use this Boombox's built-in Jellyfin
        </div>
        <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 4 }}>
          Recommended. Nothing else to configure.
        </div>
      </Card>

      <Card selected={mode === "remote"} onClick={() => setMode("remote")}>
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
              onChange={(e) => setBase(e.target.value)}
              placeholder="http://host:8096"
              autoCapitalize="off" autoCorrect="off" spellCheck={false}
              aria-label="Base URL"
              style={inputStyle}
            />
          </Field>
          <Field label="API key (optional)">
            <input
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              autoCapitalize="off" autoCorrect="off" spellCheck={false}
              aria-label="API key"
              style={inputStyle}
            />
          </Field>
        </div>
      )}

      {error && <ErrorText>{error}</ErrorText>}

      <NavRow
        onBack={back}
        primary={
          <PrimaryButton onClick={save} disabled={busy || remoteInvalid}>
            {busy ? "Saving…" : "Next"}
          </PrimaryButton>
        }
        secondary={<SecondaryButton onClick={next}>Skip</SecondaryButton>}
      />
    </StepBody>
  );
}
