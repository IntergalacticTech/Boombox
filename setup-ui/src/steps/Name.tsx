import { useState } from "react";
import type { WizardCtx } from "../App";
import type { IdentityResult } from "../lib/types";
import {
  PrimaryButton, Field, ErrorText, StepBody, NavRow, inputStyle,
} from "../components/ui";

/** Step 2 — name the device. The one required step. */
export function Name({ ctx }: { ctx: WizardCtx }) {
  const { api, summary, update, next, back } = ctx;
  const [name, setName] = useState(summary.name);
  const [renameHost, setRenameHost] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmed = name.trim();
  const valid = trimmed.length >= 1 && trimmed.length <= 32;

  const submit = async () => {
    if (!valid) {
      setError("Enter a name between 1 and 32 characters.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const r = await api.put<IdentityResult>("identity", {
        name: trimmed, rename_host: renameHost,
      });
      setBusy(false);
      if (!r.ok) {
        setError(r.error ?? "Couldn't save that name. Try another.");
        return;
      }
      update({
        name: r.name ?? trimmed,
        rebootRequired: summary.rebootRequired || !!r.reboot_required,
      });
      next();
    } catch {
      setBusy(false);
      setError("Couldn't reach the Boombox. Try again.");
    }
  };

  return (
    <StepBody
      title="Name your Boombox"
      subtitle="This is how it shows up around your home."
    >
      <Field label="Device name">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={64}
          placeholder="Living Room Boombox"
          autoCapitalize="words" autoCorrect="off" spellCheck={false}
          aria-label="Device name"
          style={inputStyle}
        />
      </Field>

      <label style={{
        display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer",
        fontSize: 14, color: "var(--ink)",
      }}>
        <input
          type="checkbox"
          checked={renameHost}
          onChange={(e) => setRenameHost(e.target.checked)}
          style={{ width: 20, height: 20, marginTop: 1, flexShrink: 0 }}
        />
        <span>
          Also rename this device on your network (used for{" "}
          <code style={{ fontFamily: "var(--mono)" }}>
            {(trimmed || "boombox").toLowerCase().replace(/[^a-z0-9]+/g, "-")
              .replace(/^-+|-+$/g, "") || "boombox"}.local
          </code>{" "}
          and the file share)
        </span>
      </label>

      {error && <ErrorText>{error}</ErrorText>}

      <NavRow
        onBack={back}
        primary={
          <PrimaryButton onClick={submit} disabled={busy || !valid}>
            {busy ? "Saving…" : "Next"}
          </PrimaryButton>
        }
      />
    </StepBody>
  );
}
