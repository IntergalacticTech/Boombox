// ButtonsPanel — Settings drawer section for the GPIO buttons service.
// Renders one row per known action with: current pin (BCM), enabled toggle,
// Test (dispatch without GPIO), and Learn (5s capture window — next falling
// edge becomes the bound pin). Config writes go to POST /api/buttons/config
// which hot-reloads in the daemon.

import { useCallback, useEffect, useState } from "react";
import { ACTION_LABELS, getConfig, learn, saveConfig, test } from "./buttonsApi";
import type { ButtonsConfig } from "./buttonsApi";

export function ButtonsPanel() {
  const [cfg, setCfg] = useState<ButtonsConfig | null>(null);
  const [learning, setLearning] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    getConfig().then(setCfg).catch(e => setStatus(`load failed: ${e.message}`));
  }, []);

  const updateRow = useCallback((action: string, patch: Partial<{ pin: number | null; enabled: boolean }>) => {
    setCfg(prev => {
      if (!prev) return prev;
      const existing = prev.pins[action] ?? { pin: null, enabled: false };
      const next: ButtonsConfig = {
        ...prev,
        pins: { ...prev.pins, [action]: { ...existing, ...patch } },
      };
      saveConfig(next).catch(e => setStatus(`save failed: ${e.message}`));
      return next;
    });
  }, []);

  const onLearn = useCallback(async (action: string) => {
    setLearning(action);
    setStatus(`press a button to bind to ${ACTION_LABELS[action] ?? action}…`);
    try {
      const r = await learn(action);
      if (r.ok && r.pin != null) {
        updateRow(action, { pin: r.pin });
        setStatus(`captured BCM${r.pin} for ${ACTION_LABELS[action] ?? action}`);
      } else {
        setStatus(r.error ?? "no press detected");
      }
    } catch (e) {
      setStatus(`learn failed: ${(e as Error).message}`);
    } finally {
      setLearning(null);
    }
  }, [updateRow]);

  const onTest = useCallback((action: string) => {
    test(action).catch(() => {});
    setStatus(`fired ${ACTION_LABELS[action] ?? action}`);
  }, []);

  return (
    <div style={{
      padding: "14px 16px",
      borderBottom: "1px solid rgba(255,255,255,0.06)",
    }}>
      <div style={{display: "flex", alignItems: "center", gap: 12, marginBottom: 10}}>
        <div style={{flex: 1, minWidth: 0}}>
          <div style={{fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em"}}>Physical buttons</div>
          <div style={{fontSize: 13, color: "rgba(255,255,255,0.65)", marginTop: 2}}>
            {cfg == null
              ? "loading…"
              : status
                ? status
                : "tap Learn, then press the wire on the panel — pin is captured live"}
          </div>
        </div>
      </div>

      {cfg && (
        <div style={{display: "grid", gap: 6}}>
          {Object.entries(ACTION_LABELS).map(([action, label]) => {
            const row = cfg.pins[action] ?? { pin: null, enabled: false };
            const isLearning = learning === action;
            return (
              <div
                key={action}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 64px 56px auto auto",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 10px",
                  background: isLearning ? "rgba(255,200,0,0.14)" : "rgba(255,255,255,0.04)",
                  border: `1px solid ${isLearning ? "rgba(255,200,0,0.45)" : "rgba(255,255,255,0.08)"}`,
                  borderRadius: 10,
                  minHeight: 48,
                  opacity: row.enabled ? 1 : 0.72,
                }}
              >
                <div style={{fontSize: 13, fontWeight: 600}}>{label}</div>
                <div style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 12,
                  textAlign: "center",
                  color: row.pin == null ? "rgba(255,255,255,0.40)" : "#5be7ff",
                }}>
                  {row.pin == null ? "—" : `BCM${row.pin}`}
                </div>
                <div style={{display: "flex", justifyContent: "center"}}>
                  <input
                    type="checkbox"
                    checked={row.enabled}
                    onChange={e => updateRow(action, { enabled: e.target.checked })}
                    style={{width: 18, height: 18, accentColor: "#7afcb0", cursor: "pointer"}}
                  />
                </div>
                <button
                  onClick={() => onTest(action)}
                  style={{...miniButton(), background: "rgba(255,255,255,0.06)"}}
                >TEST</button>
                <button
                  onClick={() => onLearn(action)}
                  disabled={learning != null}
                  style={{
                    ...miniButton(),
                    background: isLearning ? "#ffb84d" : "rgba(255,255,255,0.06)",
                    color: isLearning ? "#000" : "#fff",
                    opacity: learning != null && !isLearning ? 0.4 : 1,
                  }}
                >{isLearning ? "…" : "LEARN"}</button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function miniButton(): React.CSSProperties {
  return {
    padding: "6px 10px",
    color: "#fff",
    border: "1px solid rgba(255,255,255,0.15)",
    borderRadius: 999,
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: "0.10em",
    cursor: "pointer",
    minHeight: 32,
    flexShrink: 0,
  };
}
