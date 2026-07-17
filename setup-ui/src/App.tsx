import { useEffect, useMemo, useState } from "react";
import { makeApi, ApiProvider, useApi, type SetupApi } from "./lib/api";
import type { Status } from "./lib/types";
import { Shell, Stepper } from "./components/ui";
import { Welcome } from "./steps/Welcome";
import { Name } from "./steps/Name";
import { Wifi } from "./steps/Wifi";
import { Music } from "./steps/Music";
import { Video } from "./steps/Video";
import { Remotes } from "./steps/Remotes";
import { Done } from "./steps/Done";

/** Cross-step running summary — each step fills in its slice; the Done step
 *  reads the whole thing. */
export interface Summary {
  name: string;
  rebootRequired: boolean;
  wifiConnected: boolean;
  wifiSsid: string;
  wifiIp: string;
  musicConfigured: boolean;
  videoMode: "builtin" | "remote";
  remoteEnabled: boolean;
}

export interface WizardCtx {
  api: SetupApi;
  status: Status;
  summary: Summary;
  update: (patch: Partial<Summary>) => void;
  next: () => void;
  back: () => void;
}

const STEPS = [Welcome, Name, Wifi, Music, Video, Remotes, Done];
const TOTAL = STEPS.length;

function Wizard({ status }: { status: Status }) {
  const api = useApi();
  const [step, setStep] = useState(0);
  const [summary, setSummary] = useState<Summary>(() => ({
    name: status.identity.name,
    rebootRequired: false,
    wifiConnected: status.wifi.connected,
    wifiSsid: status.wifi.ssid,
    wifiIp: status.wifi.ip,
    musicConfigured: status.music.configured,
    videoMode: status.video.mode,
    remoteEnabled: status.remote.enabled,
  }));

  const update = (patch: Partial<Summary>) =>
    setSummary((s) => ({ ...s, ...patch }));
  const next = () => setStep((s) => Math.min(s + 1, TOTAL - 1));
  const back = () => setStep((s) => Math.max(s - 1, 0));

  const ctx: WizardCtx = { api, status, summary, update, next, back };
  const Step = STEPS[step];

  return (
    <Shell>
      <Stepper step={step} total={TOTAL} />
      <Step ctx={ctx} />
    </Shell>
  );
}

export default function App() {
  const api = useMemo(() => makeApi(), []);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.get<Status>("status")
      .then((s) => { if (alive) setStatus(s); })
      .catch(() => { if (alive) setError("Couldn't reach the Boombox setup service."); });
    return () => { alive = false; };
  }, [api]);

  if (error) {
    return (
      <Shell>
        <div style={{ textAlign: "center", color: "var(--ink2)" }}>{error}</div>
      </Shell>
    );
  }
  if (!status) {
    return (
      <Shell>
        <div style={{ textAlign: "center", color: "var(--ink2)" }}>Loading…</div>
      </Shell>
    );
  }

  return (
    <ApiProvider api={api}>
      <Wizard status={status} />
    </ApiProvider>
  );
}
