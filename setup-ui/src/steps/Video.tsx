import type { WizardCtx } from "../App";
import type { VideoResult } from "../lib/types";
import { SecondaryButton, StepBody } from "../components/ui";
import { VideoServerForm } from "../shared/VideoServerForm";

/** Step 5 — pick a video server: this Boombox's built-in Jellyfin, or a
 *  remote one. */
export function Video({ ctx }: { ctx: WizardCtx }) {
  const { api, status, update, next, back } = ctx;

  return (
    <StepBody
      title="Choose a video server"
      subtitle="Where should the Boombox stream video from?"
    >
      {/* keySet stays false: the wizard API does not promise to keep a stored
          key when none is sent. */}
      <VideoServerForm
        initial={status.video}
        keySet={false}
        onSave={async ({ mode, base, api_key }) => {
          const body = mode === "remote"
            ? { mode, base, api_key: api_key || undefined }
            : { mode };
          const r = await api.put<VideoResult>("video", body);
          if (r.ok) {
            update({ videoMode: r.mode ?? mode });
            next();
          }
          return r;
        }}
        saveLabel="Next"
        onBack={back}
        secondary={<SecondaryButton onClick={next}>Skip</SecondaryButton>}
      />
    </StepBody>
  );
}
