import type { CardState } from "./types";

const LABEL: Record<CardState, string> = { ok: "Connected", problem: "Problem",
  unset: "Not set up", absent: "Not installed" };
const COLOR: Record<CardState, string> = { ok: "#4ade80", problem: "#f87171",
  unset: "#fbbf24", absent: "#94a3b8" };

export function StatusPill({ state, detail }: { state: CardState; detail?: string }) {
  const color = COLOR[state] ?? COLOR.absent;
  return (
    <span style={{ fontSize: 12, fontWeight: 700, color,
      border: `1px solid ${color}`, borderRadius: 999, padding: "2px 10px" }}>
      {LABEL[state] ?? state}{state === "problem" && detail ? `: ${detail}` : ""}
    </span>
  );
}
