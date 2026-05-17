// SettingsDrawer — host for things that don't belong in the source / queue /
// skin pickers. Today: karaoke mic mix, library rescan, system info.
//
// Designed to fit on the 5″ screen without scrolling: each section is a
// compact row, ~60 px tall. New sections should preserve that height budget.

import { useEffect, useRef, useState } from "react";
import { ButtonsPanel } from "./ButtonsPanel";
import { PairOverlay } from "./PairOverlay";
import { UpdatesPanel } from "./UpdatesPanel";
import { LibraryPanel } from "./LibraryPanel";
import { CachePanel } from "./CachePanel";
import { setSleepMinutes, useSleepTimer } from "./sleepTimer";

type KaraokeMic = { name: string; label: string };

type KaraokeState = {
  ok: boolean;
  available: boolean;
  on: boolean;
  mic: string | null;
  mics: KaraokeMic[];
};

type SystemInfo = {
  hostname: string;
  ips?: string[];
  uptime?: string;
  temp_c?: number | null;
  airplay_name: string;
  spotify_name: string;
  bluetooth_name: string;
};

type Sink = { name: string; label: string; default: boolean; state: string };
type SinksState = { ok: boolean; default: string | null; sinks: Sink[] };

type RemoteStatus = {
  ok?: boolean;
  enabled: boolean;
  peers: { label: string; paired_at: number }[];
};
type UsbDevice = {
  id: string;
  label: string;
  mountpoint: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
};
type UsbList = { devices: UsbDevice[] };

type Props = { onClose: () => void };

export function SettingsDrawer({ onClose }: Props) {
  const [karaoke, setKaraoke] = useState<KaraokeState | null>(null);
  const [sinks, setSinks] = useState<SinksState | null>(null);
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [scanState, setScanState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [karaokePending, setKaraokePending] = useState(false);
  const [sinkPending, setSinkPending] = useState<string | null>(null);
  const [restartState, setRestartState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [remote, setRemote] = useState<RemoteStatus | null>(null);
  const [remotePending, setRemotePending] = useState(false);
  const [usb, setUsb] = useState<UsbList | null>(null);
  const [usbBusy, setUsbBusy] = useState<string | null>(null);   // `${id}:${direction}` while a copy runs
  const [usbResult, setUsbResult] = useState<string | null>(null);
  const [showPair, setShowPair] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const libraryAnchor = useRef<HTMLDivElement | null>(null);
  const nudge = (dir: 1 | -1) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollBy({ top: dir * Math.max(160, el.clientHeight * 0.7), behavior: "smooth" });
  };
  const sleepRemaining = useSleepTimer();

  const refreshKaraoke = async () => {
    try {
      const r = await fetch("/api/karaoke");
      if (r.ok) setKaraoke(await r.json());
    } catch { /* ignore */ }
  };
  const refreshSinks = async () => {
    try {
      const r = await fetch("/api/sinks");
      if (r.ok) setSinks(await r.json());
    } catch { /* ignore */ }
  };
  const refreshRemote = async () => {
    try {
      const r = await fetch("/api/remote/admin/status");
      if (r.ok) setRemote(await r.json());
    } catch { /* ignore */ }
  };
  const refreshUsb = async () => {
    try {
      const r = await fetch("/api/usb/devices");
      if (r.ok) setUsb(await r.json());
    } catch { /* ignore */ }
  };

  useEffect(() => {
    refreshKaraoke();
    refreshSinks();
    refreshRemote();
    refreshUsb();
    fetch("/api/info").then(r => r.ok ? r.json() : null).then(setInfo).catch(() => {});
    const id = setInterval(() => {
      refreshKaraoke(); refreshSinks(); refreshRemote(); refreshUsb();
    }, 4000);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    const onOpenLibrary = () => {
      libraryAnchor.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("boombox:open-settings-library", onOpenLibrary);
    window.addEventListener("boombox:scroll-to-library", onOpenLibrary);
    return () => {
      clearInterval(id);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("boombox:open-settings-library", onOpenLibrary);
      window.removeEventListener("boombox:scroll-to-library", onOpenLibrary);
    };
  }, [onClose]);

  const pickSink = async (name: string) => {
    setSinkPending(name);
    try {
      await fetch("/api/sinks/default", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      await refreshSinks();
    } finally {
      setSinkPending(null);
    }
  };

  const toggleKaraoke = async () => {
    if (!karaoke) return;
    setKaraokePending(true);
    try {
      const url = karaoke.on ? "/api/karaoke/off" : "/api/karaoke/on";
      const body = !karaoke.on && karaoke.mics.length > 0
        ? JSON.stringify({ mic: karaoke.mics[0].name })
        : "{}";
      await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      await refreshKaraoke();
    } finally {
      setKaraokePending(false);
    }
  };

  const rescanLibrary = async () => {
    setScanState("running");
    try {
      const r = await fetch("/mopidy/rpc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "core.library.refresh" }),
      });
      setScanState(r.ok ? "done" : "error");
    } catch {
      setScanState("error");
    }
    setTimeout(() => setScanState("idle"), 4000);
  };

  const toggleRemote = async () => {
    if (!remote) return;
    setRemotePending(true);
    try {
      const url = remote.enabled
        ? "/api/remote/admin/disable"
        : "/api/remote/admin/enable";
      const r = await fetch(url, { method: "POST" });
      if (r.ok) await refreshRemote();
    } finally {
      setRemotePending(false);
    }
  };

  const usbCopy = async (deviceId: string, direction: "to-library" | "to-drive") => {
    const key = `${deviceId}:${direction}`;
    if (!window.confirm(direction === "to-library"
      ? `Copy all audio from "${deviceId}" into the library?`
      : `Copy entire library to "${deviceId}"?`)) return;
    setUsbBusy(key);
    setUsbResult(null);
    try {
      const r = await fetch("/api/usb/copy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ direction, device_id: deviceId }),
      });
      if (r.ok) {
        const j = await r.json();
        setUsbResult(`copied ${j.copied?.length ?? 0} files${j.errors?.length ? ` (${j.errors.length} errors)` : ""}`);
      } else {
        setUsbResult("copy failed");
      }
    } catch {
      setUsbResult("copy failed");
    } finally {
      setUsbBusy(null);
      refreshUsb();
      setTimeout(() => setUsbResult(null), 8000);
    }
  };

  const restartMopidy = async () => {
    if (!window.confirm("Restart Mopidy? Current playback will stop briefly.")) return;
    setRestartState("running");
    try {
      const r = await fetch("/api/mopidy/restart", { method: "POST" });
      setRestartState(r.ok ? "done" : "error");
    } catch {
      setRestartState("error");
    }
    setTimeout(() => setRestartState("idle"), 5000);
  };

  return (
    <>
    {showPair && <PairOverlay onClose={() => setShowPair(false)} />}
    <div
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.92)",
        backdropFilter: "blur(20px)",
        zIndex: 9990,
        display: "flex",
        alignItems: "stretch",
        justifyContent: "center",
        padding: 12,
        fontFamily: "Inter, system-ui, sans-serif",
        color: "#fff",
      }}
    >
      <div style={{
        width: "min(960px, 100%)",
        maxHeight: "100%",
        background: "#0a0a0a",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 16,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        position: "relative",
      }}>
        {/* Floating touch-friendly scroll nudge buttons. Resistive
          * touchscreens are bad at finger-swipe; these give a
          * big, certain tap target. Top/bottom of right edge. */}
        <button
          onClick={() => nudge(-1)}
          aria-label="Scroll up"
          style={{
            position: "absolute", top: 80, right: 36,
            width: 56, height: 56, borderRadius: "50%",
            background: "rgba(79,195,247,0.85)",
            color: "#000", border: 0,
            fontSize: 28, fontWeight: 700, lineHeight: 1,
            cursor: "pointer", zIndex: 5,
            boxShadow: "0 4px 16px rgba(0,0,0,0.5)",
          }}
        >↑</button>
        <button
          onClick={() => nudge(1)}
          aria-label="Scroll down"
          style={{
            position: "absolute", bottom: 240, right: 36,
            width: 56, height: 56, borderRadius: "50%",
            background: "rgba(79,195,247,0.85)",
            color: "#000", border: 0,
            fontSize: 28, fontWeight: 700, lineHeight: 1,
            cursor: "pointer", zIndex: 5,
            boxShadow: "0 4px 16px rgba(0,0,0,0.5)",
          }}
        >↓</button>
        <div style={{
          padding: "12px 16px",
          borderBottom: "1px solid rgba(255,255,255,0.10)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexShrink: 0,
        }}>
          <div style={{flex: 1}}>
            <div style={{fontSize: 18, fontWeight: 700, letterSpacing: "-0.02em"}}>Settings</div>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10, letterSpacing: "0.18em",
              color: "rgba(255,255,255,0.5)", marginTop: 2,
            }}>{info?.hostname ? `BOOMBOX · ${info.hostname.toUpperCase()}` : "BOOMBOX"}</div>
          </div>
          <button onClick={onClose} style={{
            padding: "10px 16px",
            background: "rgba(255,255,255,0.08)",
            color: "#fff",
            border: "1px solid rgba(255,255,255,0.15)",
            borderRadius: 999,
            fontSize: 14, cursor: "pointer",
            minWidth: 64,
          }}>Close</button>
        </div>

        <div
          ref={scrollRef}
          className="settings-scroll"
          style={{
            flex: 1,
            overflowY: "auto",
            overflowX: "hidden",
            overscrollBehavior: "contain",
            touchAction: "pan-y",
            WebkitOverflowScrolling: "touch",
            padding: "8px 0",
            // Bottom padding clears the floating NowPlayingBar (~180px tall
            // including volume strip + position bar + breathing room).
            paddingBottom: 220,
            position: "relative",
          }}
        >
          {/* Movies — swap the kiosk to Jellyfin */}
          <div style={{
            padding: "14px 16px",
            borderBottom: "1px solid rgba(255,255,255,0.06)",
          }}>
            <div style={{display: "flex", alignItems: "center", gap: 14, minHeight: 48}}>
              <div style={{flex: 1, minWidth: 0}}>
                <div style={{fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em"}}>Movies</div>
                <div style={{fontSize: 13, color: "rgba(255,255,255,0.65)", marginTop: 2}}>
                  open Jellyfin on the touchscreen — a return pill appears top-left
                </div>
              </div>
              <button
                onClick={async () => {
                  // Best-effort pause Mopidy before launching the video UI so
                  // a movie's audio doesn't fight the music. We don't wait on
                  // the network — pause is idempotent and the navigation can
                  // proceed.
                  fetch("/mopidy/rpc", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "core.playback.pause" }),
                  }).catch(() => { /* fine */ });
                  // Navigate the same window so the kiosk swaps over.
                  window.location.href = "http://localhost:8096/";
                }}
                style={primaryButton("#9bf2c0")}
              >WATCH</button>
            </div>
          </div>

          {/* Phone remote */}
          <div style={{
            padding: "14px 16px",
            borderBottom: "1px solid rgba(255,255,255,0.06)",
          }}>
            <div style={{display: "flex", alignItems: "center", gap: 14, minHeight: 48}}>
              <div style={{flex: 1, minWidth: 0}}>
                <div style={{fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em"}}>Phone remote</div>
                <div style={{fontSize: 13, color: "rgba(255,255,255,0.65)", marginTop: 2}}>
                  {remote == null
                    ? "loading…"
                    : remote.enabled
                      ? `on — ${remote.peers.length} device${remote.peers.length === 1 ? "" : "s"} paired`
                      : "off — turn on to let phones pair and control the boombox"}
                </div>
              </div>
              <button
                onClick={toggleRemote}
                disabled={remote == null || remotePending}
                style={{
                  ...primaryButton(remote?.enabled ? "#ff7a35" : "#7afcb0"),
                  opacity: (remote == null || remotePending) ? 0.5 : 1,
                }}
              >{remote?.enabled ? "TURN OFF" : "TURN ON"}</button>
            </div>
            {remote?.enabled && (
              <div style={{marginTop: 12, display: "flex", flexDirection: "column", gap: 8}}>
                {remote.peers.length === 0 && (
                  <div style={{fontSize: 13, color: "rgba(255,255,255,0.5)"}}>
                    no devices paired yet — tap “Pair…” below
                  </div>
                )}
                {remote.peers.map(p => (
                  <div key={p.label + p.paired_at} style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "8px 12px",
                    background: "rgba(255,255,255,0.04)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: 10,
                  }}>
                    <div style={{flex: 1, fontWeight: 600}}>{p.label}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* USB drives */}
          <div style={{
            padding: "14px 16px",
            borderBottom: "1px solid rgba(255,255,255,0.06)",
          }}>
            <div style={{display: "flex", alignItems: "center", gap: 12, marginBottom: 10}}>
              <div style={{flex: 1}}>
                <div style={{fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em"}}>USB drives</div>
                <div style={{fontSize: 13, color: "rgba(255,255,255,0.65)", marginTop: 2}}>
                  {usb == null
                    ? "loading…"
                    : usb.devices.length === 0
                      ? "plug a drive in — its tracks will join the library automatically"
                      : `${usb.devices.length} drive${usb.devices.length === 1 ? "" : "s"} mounted`}
                </div>
              </div>
              {usbResult && (
                <div style={{fontSize: 12, color: "#7afcb0", fontFamily: "'JetBrains Mono', monospace"}}>{usbResult}</div>
              )}
            </div>
            {usb?.devices.map(d => {
              const pullKey = `${d.id}:to-library`;
              const pushKey = `${d.id}:to-drive`;
              const usedGB = (d.used_bytes / 1024 / 1024 / 1024).toFixed(1);
              const totalGB = (d.total_bytes / 1024 / 1024 / 1024).toFixed(1);
              return (
                <div key={d.id} style={{
                  padding: "10px 12px",
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: 10,
                  marginTop: 8,
                  display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
                }}>
                  <div style={{flex: 1, minWidth: 160}}>
                    <div style={{fontWeight: 700}}>{d.label}</div>
                    <div style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: 11, color: "rgba(255,255,255,0.55)", marginTop: 2,
                    }}>{usedGB} / {totalGB} GB · {d.mountpoint}</div>
                  </div>
                  <button
                    onClick={() => usbCopy(d.id, "to-library")}
                    disabled={usbBusy != null}
                    style={{...secondaryButton(), opacity: usbBusy === pullKey ? 0.5 : (usbBusy != null ? 0.4 : 1)}}
                  >{usbBusy === pullKey ? "PULLING…" : "PULL → LIBRARY"}</button>
                  <button
                    onClick={() => usbCopy(d.id, "to-drive")}
                    disabled
                    title="USB drives are mounted read-only today; push-to-drive needs the RW remount flow first."
                    style={{...secondaryButton(), opacity: usbBusy === pushKey ? 0.5 : 0.35, cursor: "default"}}
                  >PUSH SOON</button>
                </div>
              );
            })}
          </div>

          {/* Karaoke */}
          <SettingRow
            title="Karaoke"
            subtitle={
              karaoke == null
                ? "loading…"
                : karaoke.on
                  ? `mixing ${karaoke.mic ?? "default mic"} → speakers`
                  : karaoke.available
                    ? `${karaoke.mics.length} mic${karaoke.mics.length === 1 ? "" : "s"} ready`
                    : "no microphone connected"
            }
            action={
              <button
                onClick={toggleKaraoke}
                disabled={!karaoke || (!karaoke.available && !karaoke.on) || karaokePending}
                style={{
                  ...primaryButton(karaoke?.on ? "#ff7a35" : "#5be7ff"),
                  opacity: (!karaoke || (!karaoke.available && !karaoke.on) || karaokePending) ? 0.4 : 1,
                  cursor: (!karaoke || (!karaoke.available && !karaoke.on)) ? "default" : "pointer",
                }}
              >{karaoke?.on ? "TURN OFF" : "TURN ON"}</button>
            }
          />

          {/* Output sink picker */}
          <div style={{
            padding: "14px 16px",
            borderBottom: "1px solid rgba(255,255,255,0.06)",
          }}>
            <div style={{fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em", marginBottom: 10}}>Output</div>
            {sinks == null ? (
              <div style={{fontSize: 13, color: "rgba(255,255,255,0.55)"}}>loading…</div>
            ) : sinks.sinks.length === 0 ? (
              <div style={{fontSize: 13, color: "rgba(255,255,255,0.55)"}}>no sinks detected</div>
            ) : (
              <div style={{display: "flex", flexWrap: "wrap", gap: 8}}>
                {sinks.sinks.map(s => {
                  const active = s.default;
                  const pending = sinkPending === s.name;
                  return (
                    <button
                      key={s.name}
                      onClick={() => !active && pickSink(s.name)}
                      disabled={pending}
                      style={{
                        padding: "10px 14px",
                        background: active ? "#5be7ff" : "rgba(255,255,255,0.06)",
                        color: active ? "#000" : "#fff",
                        border: `1px solid ${active ? "#5be7ff" : "rgba(255,255,255,0.15)"}`,
                        borderRadius: 999,
                        fontSize: 13,
                        fontWeight: active ? 700 : 500,
                        cursor: active ? "default" : "pointer",
                        opacity: pending ? 0.6 : 1,
                        minHeight: 44,
                      }}
                    >{active ? "● " : ""}{s.label}{pending ? " …" : ""}</button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Sleep timer */}
          <div style={{
            padding: "14px 16px",
            borderBottom: "1px solid rgba(255,255,255,0.06)",
          }}>
            <div style={{display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 10}}>
              <div>
                <div style={{fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em"}}>Sleep timer</div>
                <div style={{
                  fontSize: 13, color: "rgba(255,255,255,0.65)", marginTop: 2,
                }}>
                  {sleepRemaining == null
                    ? "auto-stop after a duration"
                    : sleepRemaining === 0
                      ? "stopping…"
                      : `${formatRemain(sleepRemaining)} until stop`}
                </div>
              </div>
            </div>
            <div style={{display: "flex", flexWrap: "wrap", gap: 8}}>
              {[15, 30, 60, 120].map(m => {
                const matching = sleepRemaining != null && Math.abs(sleepRemaining - m * 60) < 30;
                return (
                  <button
                    key={m}
                    onClick={() => setSleepMinutes(m)}
                    style={{
                      padding: "10px 14px",
                      background: matching ? "#ffb84d" : "rgba(255,255,255,0.06)",
                      color: matching ? "#000" : "#fff",
                      border: `1px solid ${matching ? "#ffb84d" : "rgba(255,255,255,0.15)"}`,
                      borderRadius: 999,
                      fontSize: 13,
                      fontWeight: matching ? 700 : 500,
                      cursor: "pointer",
                      minHeight: 44,
                    }}
                  >{m} min</button>
                );
              })}
              <button
                onClick={() => setSleepMinutes(null)}
                disabled={sleepRemaining == null}
                style={{
                  padding: "10px 14px",
                  background: "transparent",
                  color: "#fff",
                  border: "1px solid rgba(255,255,255,0.15)",
                  borderRadius: 999,
                  fontSize: 13,
                  cursor: sleepRemaining == null ? "default" : "pointer",
                  opacity: sleepRemaining == null ? 0.4 : 1,
                  minHeight: 44,
                }}
              >Off</button>
            </div>
          </div>

          {/* Physical buttons — GPIO pin map + learn/test */}
          <ButtonsPanel />

          {/* Wireless remote pairing — issues a one-time PIN */}
          <SettingRow
            title="Pair wireless remote"
            subtitle="Generate a one-time PIN for a CYD or other ESP32 remote"
            action={
              <button onClick={() => setShowPair(true)} style={primaryButton("#4fc3f7")}>
                Pair…
              </button>
            }
          />

          {/* Home Library (Phase 2) — source config + offline cache */}
          <div ref={libraryAnchor}>
            <LibraryPanel />
            <CachePanel />
          </div>

          {/* Software updates — channel, window, install, rollback */}
          <UpdatesPanel />

          {/* Library rescan */}
          <SettingRow
            title="Library scan"
            subtitle={
              scanState === "running" ? "scanning music folder…"
              : scanState === "done"  ? "scan triggered — refresh to see new tracks"
              : scanState === "error" ? "scan failed"
              : "rebuild Mopidy's catalogue after adding music"
            }
            action={
              <button onClick={rescanLibrary} disabled={scanState === "running"} style={{
                ...primaryButton("#a78bfa"),
                opacity: scanState === "running" ? 0.5 : 1,
              }}>{scanState === "running" ? "SCANNING…" : "RESCAN"}</button>
            }
          />

          {/* Restart Mopidy */}
          <SettingRow
            title="Restart Mopidy"
            subtitle={
              restartState === "running" ? "restarting…"
              : restartState === "done"  ? "restarted"
              : restartState === "error" ? "restart failed (check sudoers)"
              : "use this if playback wedges"
            }
            action={
              <button onClick={restartMopidy} disabled={restartState === "running"} style={{
                ...primaryButton("#ff7a35"),
                opacity: restartState === "running" ? 0.6 : 1,
              }}>{restartState === "running" ? "…" : "RESTART"}</button>
            }
          />

          {/* Identity / discoverability */}
          <SettingRow
            title="Discoverable as"
            subtitle={info ? `${info.airplay_name} · AirPlay / Spotify · BT name “${info.bluetooth_name}”` : "loading…"}
            mono
          />

          {/* System */}
          <SettingRow
            title="System"
            subtitle={
              info
                ? [
                    info.ips?.length ? `IP ${info.ips.join(", ")}` : null,
                    info.uptime ? info.uptime.replace(/^up\s*/, "up ") : null,
                    info.temp_c != null ? `${info.temp_c.toFixed(1)} °C` : null,
                  ].filter(Boolean).join(" · ")
                : "loading…"
            }
            mono
          />
        </div>
      </div>
    </div>
    </>
  );
}

function SettingRow({ title, subtitle, action, mono }: {
  title: string;
  subtitle: string;
  action?: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div style={{
      padding: "14px 16px",
      borderBottom: "1px solid rgba(255,255,255,0.06)",
      display: "flex",
      alignItems: "center",
      gap: 14,
      minHeight: 72,
    }}>
      <div style={{flex: 1, minWidth: 0}}>
        <div style={{fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em"}}>{title}</div>
        <div style={{
          fontSize: mono ? 11 : 13,
          color: "rgba(255,255,255,0.65)",
          fontFamily: mono ? "'JetBrains Mono', monospace" : "Inter, sans-serif",
          letterSpacing: mono ? "0.06em" : "0",
          marginTop: 2,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>{subtitle}</div>
      </div>
      {action}
    </div>
  );
}

function formatRemain(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m >= 60) {
    const h = Math.floor(m / 60);
    return `${h}h ${(m % 60).toString().padStart(2, "0")}m`;
  }
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function primaryButton(accent: string): React.CSSProperties {
  return {
    padding: "10px 16px",
    background: accent,
    color: "#000",
    border: "none",
    borderRadius: 999,
    fontWeight: 700,
    fontSize: 12,
    letterSpacing: "0.10em",
    cursor: "pointer",
    flexShrink: 0,
  };
}

function secondaryButton(): React.CSSProperties {
  return {
    padding: "8px 12px",
    background: "rgba(255,255,255,0.06)",
    color: "#fff",
    border: "1px solid rgba(255,255,255,0.18)",
    borderRadius: 999,
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: "0.10em",
    cursor: "pointer",
    flexShrink: 0,
  };
}
