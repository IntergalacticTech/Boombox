import { useEffect, useMemo, useRef, useState } from "react";
import { makeApi, ApiProvider, useApi, type SetupApi } from "./lib/api";
import type { RedeemResult, Status } from "./lib/types";
import {
  PrimaryButton, ErrorText, Shell, StepBody, Stepper, inputStyle,
} from "./components/ui";
import { Welcome } from "./steps/Welcome";
import { Name } from "./steps/Name";
import { Wifi } from "./steps/Wifi";
import { Music } from "./steps/Music";
import { Video } from "./steps/Video";
import { Skin } from "./steps/Skin";
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
  skin: string;
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

const STEPS = [Welcome, Name, Wifi, Music, Video, Skin, Remotes, Done];
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
    skin: status.skin || "",
    remoteEnabled: status.remote.enabled,
  }));

  // Kiosk only: if setup was incomplete when the wizard loaded, watch for it
  // being finished FROM A PHONE and hand the kiosk back to the player (with
  // the chosen skin). Without this the touchscreen would sit on the wizard
  // after a phone-driven setup. Guarded on the initial complete flag so a
  // deliberately re-opened wizard (Settings → Setup wizard) never bounces.
  const wasIncomplete = useRef(!status.complete);
  useEffect(() => {
    if (!api.isKiosk || !wasIncomplete.current) return;
    const t = setInterval(async () => {
      try {
        const s = await api.get<Status>("status");
        if (s.complete) {
          const skin = s.skin ? `?skin=${encodeURIComponent(s.skin)}` : "";
          window.location.replace(`/${skin}`);
        }
      } catch { /* service briefly unreachable — keep polling */ }
    }, 4000);
    return () => clearInterval(t);
  }, [api]);

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

/** Typed-URL entry: a LAN visitor without a hash token exchanges the 6-digit
 *  code shown on the boombox screen for the setup token. */
function CodeEntry({ onDone }: { onDone: () => void }) {
  const api = useApi();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const redeem = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await api.post<RedeemResult>("session/redeem", { code: code.trim() });
      setBusy(false);
      if (!r.ok || !r.token) {
        setError(r.error || "Wrong code — check the boombox screen.");
        return;
      }
      api.adoptToken(r.token);
      onDone();
    } catch {
      setBusy(false);
      setError("Couldn't reach the Boombox. Same Wi-Fi network?");
    }
  };

  return (
    <Shell>
      <StepBody
        title="Enter the setup code"
        subtitle="It's the 6-digit code on the Boombox's screen."
      >
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="123456"
          aria-label="Setup code"
          style={{
            ...inputStyle,
            fontSize: 32, letterSpacing: "0.35em", textAlign: "center",
            fontFamily: "var(--mono)",
          }}
        />
        {error && <ErrorText>{error}</ErrorText>}
        <PrimaryButton onClick={redeem} disabled={busy || code.length !== 6}>
          {busy ? "Checking…" : "Continue"}
        </PrimaryButton>
      </StepBody>
    </Shell>
  );
}

export default function App() {
  const api = useMemo(() => makeApi(), []);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authed, setAuthed] = useState(() => api.isKiosk || api.token !== null);

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
  if (!authed) {
    return (
      <ApiProvider api={api}>
        <CodeEntry onDone={() => setAuthed(true)} />
      </ApiProvider>
    );
  }

  return (
    <ApiProvider api={api}>
      <Wizard status={status} />
    </ApiProvider>
  );
}
