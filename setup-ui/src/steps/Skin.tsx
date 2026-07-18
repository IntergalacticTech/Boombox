import { useState } from "react";
import type { WizardCtx } from "../App";
import type { OkResult } from "../lib/types";
import { SKIN_CHOICES, type SkinChoice } from "../lib/skins";
import {
  PrimaryButton, SecondaryButton, ErrorText, StepBody, NavRow,
} from "../components/ui";

function Swatch({ colors }: { colors: SkinChoice["swatch"] }) {
  return (
    <span style={{ display: "inline-flex", gap: 4 }}>
      {colors.map((c, i) => (
        <span key={i} style={{
          width: 16, height: 16, borderRadius: 4, background: c,
          border: "1px solid var(--rule)",
        }} />
      ))}
    </span>
  );
}

/** Pick the touchscreen's look. Selection is stored server-side so a choice
 *  made on a phone reaches the kiosk; on the kiosk itself we ALSO write
 *  localStorage (same origin as the player) so the skin applies the moment
 *  the wizard hands back to the player. */
export function Skin({ ctx }: { ctx: WizardCtx }) {
  const { api, status, summary, update, next, back } = ctx;
  const [selected, setSelected] = useState<string>(
    summary.skin || status.skin || "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (!selected) { next(); return; }
    setError(null);
    setBusy(true);
    try {
      const r = await api.put<OkResult>("skin", { id: selected });
      setBusy(false);
      if (!r.ok) { setError(r.error || "Couldn't save the skin."); return; }
      if (api.isKiosk) {
        try { localStorage.setItem("boombox.skin", selected); } catch { /* fine */ }
      }
      update({ skin: selected });
      next();
    } catch {
      setBusy(false);
      setError("Couldn't save the skin. Try again.");
    }
  };

  return (
    <StepBody
      title="Pick a skin"
      subtitle="The touchscreen's look. You can change it anytime from the player."
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {SKIN_CHOICES.map((s) => {
          const active = selected === s.id;
          return (
            <button
              key={s.id}
              onClick={() => setSelected(s.id)}
              style={{
                display: "flex", alignItems: "center", gap: 14,
                textAlign: "left", padding: "12px 14px", borderRadius: 12,
                background: active ? "var(--panel)" : "transparent",
                border: `2px solid ${active ? "var(--accent)" : "var(--rule)"}`,
                color: "var(--ink)", cursor: "pointer", minHeight: 56,
                font: "inherit",
              }}
            >
              <Swatch colors={s.swatch} />
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: "block", fontWeight: 700, fontSize: 15 }}>
                  {s.name}
                </span>
                <span style={{
                  display: "block", color: "var(--ink2)", fontSize: 12.5,
                  marginTop: 1,
                }}>
                  {s.blurb}
                </span>
              </span>
              {active && (
                <span aria-hidden style={{ color: "var(--accent)", fontSize: 18 }}>✓</span>
              )}
            </button>
          );
        })}
      </div>

      {error && <ErrorText>{error}</ErrorText>}

      <NavRow
        onBack={back}
        primary={
          <PrimaryButton onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Next"}
          </PrimaryButton>
        }
        secondary={
          <SecondaryButton onClick={next}>Skip</SecondaryButton>
        }
      />
    </StepBody>
  );
}
