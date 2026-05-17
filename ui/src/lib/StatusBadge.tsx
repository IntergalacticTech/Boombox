// StatusBadge — inline glyph for Home Library track rows.
// Tells the user at a glance whether a track is pinned, cached, streaming
// right now, or catalog-only. Pure presentational; no state of its own.

type CacheStatus = "present" | "absent" | "queued" | "downloading" | "error";

type Props = {
  cacheStatus: CacheStatus;
  isCurrentTrack: boolean;   // currently playing AND streaming
  pinned: boolean;
};

export function StatusBadge({ cacheStatus, isCurrentTrack, pinned }: Props) {
  // Resolution priority: ⚡ (live stream) > 📌 (pinned, downloading) > ⬇ (cached) > ⚠ (error) > ☁ (catalog).
  let glyph = "";
  let title = "";
  if (isCurrentTrack && cacheStatus !== "present") {
    glyph = "⚡"; title = "Streaming";
  } else if (pinned && cacheStatus !== "present") {
    glyph = "📌"; title = "Pinned · download pending";
  } else if (cacheStatus === "present") {
    glyph = "⬇"; title = pinned ? "Pinned · cached" : "Cached";
  } else if (cacheStatus === "error") {
    glyph = "⚠"; title = "Download error";
  } else {
    glyph = "☁"; title = "Catalog only";
  }
  return (
    <span
      title={title}
      aria-label={title}
      style={{
        display: "inline-grid",
        placeItems: "center",
        width: 20, height: 20,
        fontSize: 12,
        opacity: 0.85,
        flexShrink: 0,
      }}
    >{glyph}</span>
  );
}
