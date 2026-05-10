import { useEffect, useState } from "react";
import { useMopidy, useElapsed } from "./lib/mopidy";
import { useActiveSource, isExternalActive, controlExternal } from "./lib/activeSource";
import { ScaleToFit } from "./lib/scaleToFit";
import { SkinPickerDrawer } from "./lib/SkinPicker";
import { SourceDrawer } from "./lib/SourceSwitcher";
import { QueueDrawer } from "./lib/QueueDrawer";
import { LibraryDrawer } from "./lib/LibraryDrawer";
import { SettingsDrawer } from "./lib/SettingsDrawer";
import { NowPlayingBar } from "./lib/NowPlayingBar";
import { VolumeGesture } from "./lib/VolumeGesture";
import { SKIN_BY_ID, SKINS, type ChromeApi } from "./lib/skinRegistry";
import { getQueue } from "./lib/library";
import type { SkinId, Track, PlayState } from "./lib/types";

function getActiveSkin(): SkinId {
  const params = new URLSearchParams(window.location.search);
  const fromQuery = params.get("skin") as SkinId | null;
  if (fromQuery && SKIN_BY_ID[fromQuery]) {
    localStorage.setItem("boombox.skin", fromQuery);
    return fromQuery;
  }
  const stored = localStorage.getItem("boombox.skin") as SkinId | null;
  if (stored && SKIN_BY_ID[stored]) return stored;
  return "deckos";
}

const SOURCE_COLOR: Record<string, string> = {
  library: "#5be7ff",
  airplay: "#a78bfa",
  spotify: "#1ed760",
  bluetooth: "#5b9aff",
  idle:   "rgba(255,255,255,0.35)",
};

function App() {
  const m = useMopidy();
  const elapsed = useElapsed(m.state, m.positionMs, m.positionAtMs);
  const ext = useActiveSource(2000);

  const skinId = getActiveSkin();
  const skin = SKIN_BY_ID[skinId] ?? SKINS[0];
  const Audio = skin.Audio;

  const [sourceOpen, setSourceOpen] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [skinPickerOpen, setSkinPickerOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Queue length poll for the chrome badge.
  const [queueCount, setQueueCount] = useState(0);
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const q = await getQueue();
        if (!cancelled) setQueueCount(q.length);
      } catch { /* ignore */ }
    };
    tick();
    const id = setInterval(tick, 4000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Publish the active skin's theme so external surfaces (the LAN upload
  // page, etc.) can match the kiosk's look. Best-effort; offline is fine.
  useEffect(() => {
    fetch("/api/theme", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skinId: skin.id, name: skin.name, theme: skin.theme }),
    }).catch(() => { /* boombox-state offline; no harm */ });
  }, [skin.id]);

  // External source overrides Mopidy's state when it's the live player.
  const externalActive = isExternalActive(ext);
  const trackForSkin: Track | null = externalActive && ext.track
    ? {
        uri: `mpris:${ext.source ?? ""}`,
        title: ext.track.title || "—",
        artist: ext.track.artist || "—",
        album: ext.track.album || "",
        len: Math.max(0, Math.floor(ext.length_ms / 1000)),
        time: formatTime(ext.length_ms),
        hue: hashHue(ext.track.title || ext.source || "x"),
      }
    : m.track;
  const stateForSkin: PlayState = externalActive
    ? (ext.status as PlayState)
    : m.state;
  const elapsedForSkin = externalActive
    ? Math.max(0, ext.position_ms / 1000)
    : elapsed;

  // Transport actions route to whichever source is the active player.
  // Mopidy's HTTP API is preferred when available because of its richer
  // semantics (handles both stopped→play and pause→play with one call);
  // for external players we POST to /api/control/<action>.
  const onToggle = externalActive ? () => controlExternal("toggle") : m.toggle;
  const onNext   = externalActive ? () => controlExternal("next")   : m.next;
  const onPrev   = externalActive ? () => controlExternal("previous"): m.prev;
  // Seek only works for Mopidy. External MPRIS sources rarely accept Position
  // writes, so we just no-op when an external source is the live player.
  const onSeek = externalActive ? undefined : (sec: number) => m.seek(sec * 1000);

  // Source identity for the chrome bar — shows which input is currently
  // producing audio; falls back to "LIBRARY" when Mopidy is the producer.
  const sourceId = computeSourceId(ext.source, ext.status, m.state === "playing");
  const chrome: ChromeApi = {
    sourceLabel: sourceId.toUpperCase(),
    sourceColor: SOURCE_COLOR[sourceId] ?? SOURCE_COLOR.idle,
    sourceLive: sourceId !== "idle" && sourceId !== "library",
    queueCount,
    skinName: skin.name,
    onOpenSource: () => setSourceOpen(true),
    onOpenQueue: () => setQueueOpen(true),
    onOpenSkinPicker: () => setSkinPickerOpen(true),
    onOpenSettings: () => setSettingsOpen(true),
  };

  return (
    <>
      <ScaleToFit width={1280} height={800}>
        <Audio
          track={trackForSkin}
          state={stateForSkin}
          elapsed={elapsedForSkin}
          volume={m.volume}
          shuffle={m.shuffle}
          repeat={m.repeat}
          chrome={chrome}
          onToggle={onToggle}
          onNext={onNext}
          onPrev={onPrev}
          onToggleShuffle={m.toggleShuffle}
          onToggleRepeat={m.toggleRepeat}
          onSeek={onSeek}
        />
      </ScaleToFit>
      <VolumeGesture />
      {sourceOpen && (
        <SourceDrawer
          ext={ext}
          mopidyPlaying={m.state === "playing"}
          onClose={() => setSourceOpen(false)}
          onOpenLibrary={() => { setLibraryOpen(true); setSourceOpen(false); }}
        />
      )}
      {queueOpen && <QueueDrawer onClose={() => setQueueOpen(false)} />}
      {libraryOpen && <LibraryDrawer onClose={() => setLibraryOpen(false)} />}
      {skinPickerOpen && <SkinPickerDrawer activeId={skinId} onClose={() => setSkinPickerOpen(false)} />}
      {settingsOpen && <SettingsDrawer onClose={() => setSettingsOpen(false)} />}
      {(sourceOpen || queueOpen || libraryOpen || skinPickerOpen || settingsOpen) && <NowPlayingBar />}
    </>
  );
}

function computeSourceId(source: string | null, status: string, mopidyPlaying: boolean): "library" | "airplay" | "spotify" | "bluetooth" | "idle" {
  const live = status === "playing" || status === "paused";
  if (live && source) {
    const s = source.toLowerCase();
    if (s.includes("shairport") || s.includes("airplay")) return "airplay";
    if (s.includes("spotify") || s.includes("librespot") || s.includes("raspotify")) return "spotify";
    if (s.includes("bluez") || s.includes("blue")) return "bluetooth";
  }
  return mopidyPlaying ? "library" : "idle";
}

function formatTime(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function hashHue(seed: string): number {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = ((h << 5) - h + seed.charCodeAt(i)) | 0;
  return Math.abs(h) % 360;
}

export default App;
