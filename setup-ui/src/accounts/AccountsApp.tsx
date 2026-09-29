import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Shell, ErrorText } from "../components/ui";
import { accountsApi } from "./api";
import type { Summary, CardStatus } from "./types";
import { StatusPill } from "./StatusPill";
import { MusicCard } from "./MusicCard";
import { VideoCard } from "./VideoCard";
import { StreamingCard } from "./StreamingCard";
import { WebLoginCard } from "./WebLoginCard";

export const UNREACHABLE = "Couldn't reach the Boombox.";

function Section({ title, status, children }: { title: string; status?: CardStatus; children: ReactNode }) {
  return (
    <section style={{ border: "1px solid var(--rule)", borderRadius: 14, padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
        flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <h2 style={{ fontSize: 18, margin: 0 }}>{title}</h2>
        {status && <StatusPill state={status.state} detail={status.detail} />}
      </div>
      {children}
    </section>
  );
}

export function AccountsApp() {
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
    <Shell>
      <h1 style={{ fontSize: 24, margin: 0 }}>Accounts</h1>
      {error && <ErrorText>{error}</ErrorText>}
      <Section title="Music server" status={summary?.music}><MusicCard onChanged={refresh} /></Section>
      <Section title="Video server" status={summary?.video}><VideoCard onChanged={refresh} /></Section>
      <Section title="Streaming receivers" status={summary?.streaming}><StreamingCard onChanged={refresh} /></Section>
      <Section title="Boombox web login" status={summary?.web}><WebLoginCard /></Section>
    </Shell>
  );
}
