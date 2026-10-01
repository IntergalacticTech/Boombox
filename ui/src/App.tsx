import { useEffect, useRef, useState } from "react";
import { useMopidy, useElapsed } from "./lib/mopidy";
import { useActiveSource, isExternalActive, isAsleep, controlExternal } from "./lib/activeSource";
import { ScaleToFit } from "./lib/scaleToFit";
import { SkinPickerDrawer } from "./lib/SkinPicker";
import { HomeScreen } from "./lib/HomeScreen";
import { SleepScreen } from "./lib/SleepScreen";
import { activeIdFor, accentFor, chromeLabelFor, isExternalId } from "./lib/sources";
import { QueueDrawer } from "./lib/QueueDrawer";
import { LibraryDrawer } from "./lib/LibraryDrawer";
import { SettingsDrawer } from "./lib/SettingsDrawer";
import { NowPlayingBar } from "./lib/NowPlayingBar";
import { VolumeGesture } from "./lib/VolumeGesture";
import { OverlayRoot } from "./overlays/OverlayRoot";
import { SKIN_BY_ID, SKINS, type ChromeApi } from "./lib/skinRegistry";
import { getQueue } from "./lib/library";
import { getCacheCandidates } from "./lib/libraryApi";
import { useSyncStatus } from "./lib/homeLibrary";
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

function App() {
  const m = useMopidy();
  const elapsed = useElapsed(m.state, m.positionMs, m.positionAtMs);
  const ext = useActiveSource(2000);

  const skinId = getActiveSkin();
  const skin = SKIN_BY_ID[skinId] ?? SKINS[0];
  const Audio = skin.Audio;

  // The box boots to Home and only enters the player once the user picks an
  // input (or taps the Now Playing strip). Nothing is persisted: a reboot is
  // meant to land on Home, and that's what a fresh mount does.
  const [view, setView] = useState<"home" | "player">("home");
  const [queueOpen, setQueueOpen] = useState(false);
  const [skinPickerOpen, setSkinPickerOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Per-drawer-session dismissal of the floating NowPlayingBar. Resets
  // to true any time a drawer opens, so the player is back next time.
  const [npbDismissed, setNpbDismissed] = useState(false);

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

  // Phase 2: SyncIndicator chip in the chrome dispatches this event when
  // tapped. App opens SettingsDrawer here, then re-fires the event after
  // the drawer has mounted its own scroll-to-library listener (~120 ms
  // covers the drawer's initial fetch tick).
  useEffect(() => {
    const onOpenLib = () => {
      setSettingsOpen(true);
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent("boombox:scroll-to-library"));
      }, 150);
    };
    window.addEventListener("boombox:open-settings-library", onOpenLib);
    return () => window.removeEventListener("boombox:open-settings-library", onOpenLib);
  }, []);

  // RFID bind flow: when RfidBindOverlay starts a bind, open LibraryDrawer
  // and track the UID in App state — passing it to LibraryDrawer as a
  // prop is the only reliable way (the drawer is unmounted at the moment
  // the event fires, so a window listener inside it can't catch it).
  const [bindUid, setBindUid] = useState<string | null>(null);
  useEffect(() => {
    const onBindStart = (e: Event) => {
      const detail = (e as CustomEvent).detail as { uid: string };
      setBindUid(detail.uid);
      setLibraryOpen(true);
    };
    const onBindClear = () => setBindUid(null);
    window.addEventListener("boombox:rfid-bind-start", onBindStart);
    window.addEventListener("boombox:rfid-bind-clear", onBindClear);
    return () => {
      window.removeEventListener("boombox:rfid-bind-start", onBindStart);
      window.removeEventListener("boombox:rfid-bind-clear", onBindClear);
    };
  }, []);

  // Phase 2: poll for unadopted USB drives. Only prompt while no cache drive
  // is currently adopted — otherwise plugging a second drive would steal the
  // cache role. CacheAdoptOverlay listens for the dispatched event.
  const syncStatus = useSyncStatus();
  useEffect(() => {
    if (syncStatus.cachePresent) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const cands = await getCacheCandidates();
        if (cancelled || cands.length === 0) return;
        window.dispatchEvent(new CustomEvent("boombox:cache-candidate", { detail: cands[0] }));
      } catch { /* offline / 404 — quiet */ }
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, [syncStatus.cachePresent]);

  // Standby. `asleep` is whatever boombox-state last said; a server that
  // doesn't report power (or is down) reads as awake, so the kiosk can never
  // strand itself behind the black SleepScreen.
  const asleep = isAsleep(ext);
  const wasAsleep = useRef(asleep);
  useEffect(() => {
    // Waking is an "appliance turned on" moment, not a resume: the user gets
    // the Home picker with nothing else on top, whatever they left open.
    if (wasAsleep.current && !asleep) {
      setView("home");
      setQueueOpen(false);
      setLibraryOpen(false);
      setSkinPickerOpen(false);
      setSettingsOpen(false);
      setBindUid(null);
    }
    wasAsleep.current = asleep;
  }, [asleep]);

  // Publish the active skin's theme so external surfaces (the LAN upload
  // page, etc.) can match the kiosk's look. Best-effort; offline is fine.
  useEffect(() => {
    fetch("/api/theme", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skinId: skin.id, name: skin.name, theme: skin.theme }),
    }).catch(() => { /* boombox-state offline; no harm */ });
  }, [skin.id, skin.name, skin.theme]);

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
  const sourceId = activeIdFor(ext.source, ext.status, m.state === "playing");
  const goHome = () => { setNpbDismissed(false); setView("home"); };
  const anyDrawerOpen = queueOpen || libraryOpen || skinPickerOpen || settingsOpen;

  const openLibrary = () => { setNpbDismissed(false); setLibraryOpen(true); };
  const chrome: ChromeApi = {
    sourceLabel: chromeLabelFor(sourceId),
    sourceColor: accentFor(sourceId),
    sourceLive: isExternalId(sourceId),
    queueCount,
    skinName: skin.name,
    onGoHome: goHome,
    onOpenQueue: () => { setNpbDismissed(false); setQueueOpen(true); },
    onOpenLibrary: openLibrary,
    onOpenSkinPicker: () => { setNpbDismissed(false); setSkinPickerOpen(true); },
    onOpenSettings: () => { setNpbDismissed(false); setSettingsOpen(true); },
  };

  return (
    <>
      <OverlayRoot />
      <ScaleToFit width={1280} height={800}>
        {view === "home" ? (
          // The skin's Audio component is deliberately unmounted on Home: its
          // spectrum/VU animations would keep running (and keep the Pi's GPU
          // busy) behind a screen that isn't showing them.
          <HomeScreen
            theme={skin.theme}
            queueCount={queueCount}
            onGoPlayer={() => setView("player")}
            onOpenLibrary={openLibrary}
            onOpenSettings={() => { setNpbDismissed(false); setSettingsOpen(true); }}
            showNowPlaying={!anyDrawerOpen}
          />
        ) : (
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
        )}
      </ScaleToFit>
      <VolumeGesture />
      {queueOpen && (
        <QueueDrawer
          onClose={() => setQueueOpen(false)}
          onHome={() => { setQueueOpen(false); goHome(); }}
        />
      )}
      {libraryOpen && (
        <LibraryDrawer
          onClose={() => { setLibraryOpen(false); setBindUid(null); }}
          onHome={() => { setLibraryOpen(false); setBindUid(null); goHome(); }}
          bindUid={bindUid}
        />
      )}
      {skinPickerOpen && (
        <SkinPickerDrawer
          activeId={skinId}
          onClose={() => setSkinPickerOpen(false)}
          onHome={() => { setSkinPickerOpen(false); goHome(); }}
        />
      )}
      {settingsOpen && (
        <SettingsDrawer
          onClose={() => setSettingsOpen(false)}
          onHome={() => { setSettingsOpen(false); goHome(); }}
        />
      )}
      {anyDrawerOpen && !npbDismissed && (
        <NowPlayingBar onDismiss={() => setNpbDismissed(true)} />
      )}
      {/* Last child, highest z-index: while asleep nothing below is reachable. */}
      {asleep && <SleepScreen />}
    </>
  );
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
