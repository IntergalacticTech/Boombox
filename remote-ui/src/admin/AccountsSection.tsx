import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ErrorText, SecondaryButton } from "./ui";
import { accountsApi } from "./accounts/api";
import type { Summary, CardStatus } from "./accounts/types";
import { StatusPill } from "./accounts/StatusPill";
import { MusicCard } from "./accounts/MusicCard";
import { VideoCard } from "./accounts/VideoCard";
import { StreamingCard } from "./accounts/StreamingCard";
import { WebLoginCard } from "./accounts/WebLoginCard";
import { LockScreen } from "./LockScreen";
import { lock, useAdminSession } from "./session";

export const UNREACHABLE = "Couldn't reach the Boombox.";

function Section({ title, status, children }: {
  title: string; status?: CardStatus; children: ReactNode;
}) {
  return (
    <section style={{ border: "1px solid var(--rule)", borderRadius: 14, padding: 16, minWidth: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
        flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <h2 style={{ fontSize: 18, margin: 0 }}>{title}</h2>
        {status && <StatusPill state={status.state} detail={status.detail} />}
      </div>
      {children}
    </section>
  );
}

function AccountsCards({ desktop }: { desktop: boolean }) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    accountsApi.get<Summary & { error?: string }>("summary").then((s) => {
      if (s && s.music) { setSummary(s); setError(null); }
      else setError(s?.error ?? UNREACHABLE);
    }).catch(() => setError(UNREACHABLE));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  return (
    <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 16 }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <h1 style={{ fontSize: 24, margin: 0 }}>Accounts</h1>
        <SecondaryButton aria-label="Lock admin" onClick={() => void lock()}
                         style={{ width: "auto", minHeight: 40, padding: "8px 14px" }}>
          🔒 Lock
        </SecondaryButton>
      </header>
      {error && <ErrorText>{error}</ErrorText>}
      <div data-testid="accounts-grid" data-columns={desktop ? 2 : 1} style={{
        display: "grid", gap: 16, alignItems: "start",
        gridTemplateColumns: desktop ? "repeat(2, minmax(0, 1fr))" : "minmax(0, 1fr)",
      }}>
        <Section title="Music server" status={summary?.music}><MusicCard onChanged={refresh} /></Section>
        <Section title="Video server" status={summary?.video}><VideoCard onChanged={refresh} /></Section>
        <Section title="Streaming receivers" status={summary?.streaming}>
          <StreamingCard onChanged={refresh} /></Section>
        <Section title="Boombox web login" status={summary?.web}><WebLoginCard /></Section>
      </div>
    </div>
  );
}

/** Admin → Accounts: the four Accounts cards, behind the web password. */
export function AccountsSection({ desktop }: { desktop: boolean }) {
  const { unlocked, expired } = useAdminSession();
  if (!unlocked) return <LockScreen expired={expired} />;
  return <AccountsCards desktop={desktop} />;
}
