import type { WizardCtx } from "../App";
import type { MusicTestResult, OkResult } from "../lib/types";
import { SecondaryButton, StepBody } from "../components/ui";
import { MusicForm } from "../shared/MusicForm";

/** Step 4 — connect a Navidrome / Subsonic music library. */
export function Music({ ctx }: { ctx: WizardCtx }) {
  const { api, status, update, next, back } = ctx;

  return (
    <StepBody
      title="Connect your music"
      subtitle="Point the Boombox at your Navidrome or Subsonic library."
    >
      {/* passwordSet stays false: the wizard API saves whatever password it
          is sent, so "leave blank to keep" would be a lie here. */}
      <MusicForm
        initial={status.music}
        passwordSet={false}
        onTest={(v) => api.post<MusicTestResult>("music/test", v)}
        onSave={async (v) => {
          // The server re-tests the connection before saving; a 400 means
          // the URL/credentials failed — do not advance.
          const r = await api.put<OkResult>("music", v);
          if (r.ok) {
            update({ musicConfigured: true });
            next();
          }
          return r;
        }}
        saveLabel="Save & continue"
        onBack={back}
        secondary={<SecondaryButton onClick={next}>Skip for now</SecondaryButton>}
      />
    </StepBody>
  );
}
