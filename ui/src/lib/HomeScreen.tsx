// HomeScreen — the boombox's front door. Cold boot and every wake land here,
// and it replaces the old SourceDrawer: instead of a modal list of sources on
// top of a Now Playing surface that was always running, the box starts at a
// picker and only enters the player once the user chooses an input.
//
// Rendered inside ScaleToFit's 1280×800 design space, so the numbers below are
// design pixels: on the 7" 800×480 panel everything is multiplied by 0.6. A
// 240-px tile is therefore a 144-px target — deliberately huge, because this
// is a resistive panel poked with a thumb from across a kitchen.
//
// Themed from the active skin so Home doesn't feel bolted on: the skin picks
// bg/panel/ink/accent, the per-source accents stay constant (a green Spotify
// tile reads as Spotify in every skin).

import { useEffect, useState } from "react";
import { CARDS, type SourceId } from "./sources";
import { NowPlayingBar } from "./NowPlayingBar";
import type { SkinTheme } from "./skinRegistry";

type Props = {
  theme: SkinTheme;
  /** Mopidy tracklist length — Music jumps straight to the library when empty. */
  queueCount: number;
  onGoPlayer: () => void;
  onOpenLibrary: () => void;
  onOpenSettings: () => void;
  /** False while a drawer is open — App floats its own NowPlayingBar above
   * the drawer then, and two bars would stack. Default true. */
  showNowPlaying?: boolean;
};

/** Tiles that aren't inputs. Kept apart from CARDS so sources.ts stays a
 * description of the audio pipeline and nothing else. */
const SETTINGS_TILE = { name: "Settings", tag: "SYSTEM", accent: "#9aa4b2", glyph: "⚙" };
// "◯" rather than the IEC power symbol ⏻ — Inter has no glyph for it, and a
// tofu box on the Off tile is exactly the wrong thing to ship.
const OFF_TILE = { name: "Off", tag: "STANDBY", accent: "#ff5466", glyph: "◯" };

export function HomeScreen({
  theme, queueCount, onGoPlayer, onOpenLibrary, onOpenSettings, showNowPlaying = true,
}: Props) {
  // AUX (and any other purely informational tile) reveals its blurb in place
  // rather than opening anything — there is nothing for the Pi to do.
  const [info, setInfo] = useState<SourceId | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [jellyfinBase, setJellyfinBase] = useState<string | null>(null);

  // The wizard may point Video at an off-device Jellyfin; /api/info carries it.
  // Fetched up front so the tile navigates on the first tap with no latency.
  useEffect(() => {
    let cancelled = false;
    fetch("/api/info")
      .then(r => (r.ok ? r.json() : null))
      .then(j => { if (!cancelled && j?.jellyfin_base) setJellyfinBase(j.jellyfin_base); })
      .catch(() => { /* offline — the localhost fallback is right anyway */ });
    return () => { cancelled = true; };
  }, []);

  const showOverlay = (source: SourceId) => {
    // Same event the GPIO source buttons emit; SourceInstructionOverlay owns
    // the copy and the auto-dismiss.
    window.dispatchEvent(new CustomEvent("boombox:source-overlay", { detail: { source } }));
  };

  const triggerCard = (id: SourceId) => {
    setInfo(null);
    if (id === "mopidy") {
      onGoPlayer();
      // Nothing queued means the player would be an empty stage; go straight
      // to the library so the first tap after boot lands on something to play.
      if (queueCount === 0) onOpenLibrary();
      return;
    }
    if (id === "movies") {
      // Best-effort pause Mopidy so a movie's audio doesn't fight music, then
      // swap the kiosk over. The kiosk extension's return pill brings the user
      // back to "/" — i.e. to Home.
      fetch("/mopidy/rpc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "core.playback.pause" }),
      }).catch(() => { /* fine */ });
      // .assign() rather than `location.href =` so the lint rule that guards
      // against render-phase mutation doesn't have to reason about it.
      window.location.assign(jellyfinBase || "http://localhost:8096/");
      return;
    }
    if (id === "bluetooth") {
      fetch("/api/bluetooth/pair", { method: "POST" }).catch(() => { /* overlay still helps */ });
      onGoPlayer();
      showOverlay(id);
      return;
    }
    if (id === "airplay" || id === "spotify") {
      // Nothing to switch on — the receiver is always listening. We move to
      // the player so the incoming stream has somewhere to land, and show the
      // "pick Boombox on your phone" card over it.
      onGoPlayer();
      showOverlay(id);
      return;
    }
    setInfo(id);   // aux
  };

  const sleep = () => {
    setNote("going to sleep…");
    // Failures are silent by design: /api/state is the truth and the tile
    // re-enables itself, so a flaky POST just means nothing happened.
    fetch("/api/power/sleep", { method: "POST" })
      .catch(() => setNote("could not reach the power service"));
    setTimeout(() => setNote(null), 4000);
  };

  const infoCard = info ? CARDS.find(c => c.id === info) ?? null : null;

  return (
    <div style={{
      width: 1280,
      height: 800,
      background: theme.bg,
      color: theme.ink,
      fontFamily: theme.font,
      display: "flex",
      flexDirection: "column",
      padding: "28px 40px 0",
      boxSizing: "border-box",
      overflow: "hidden",
    }}>
      <div style={{display: "flex", alignItems: "baseline", gap: 16, height: 54, flexShrink: 0}}>
        <div style={{fontSize: 30, fontWeight: 800, letterSpacing: "-0.02em"}}>Boombox</div>
        <div style={{
          fontFamily: theme.mono,
          fontSize: 12,
          letterSpacing: "0.22em",
          color: theme.ink2,
        }}>CHOOSE AN INPUT</div>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        // Two rows of 260 fill the panel down to the message strip and still
        // leave room for the Now Playing bar underneath.
        gridAutoRows: 260,
        gap: 18,
        flexShrink: 0,
      }}>
        {CARDS.map(c => (
          <Tile
            key={c.id}
            theme={theme}
            name={c.name}
            tag={c.tag}
            glyph={c.glyph || c.name[0]}
            accent={c.accent}
            onClick={() => triggerCard(c.id)}
          />
        ))}
        <Tile
          theme={theme}
          name={SETTINGS_TILE.name}
          tag={SETTINGS_TILE.tag}
          glyph={SETTINGS_TILE.glyph}
          accent={SETTINGS_TILE.accent}
          onClick={onOpenSettings}
        />
        <Tile
          theme={theme}
          name={OFF_TILE.name}
          tag={OFF_TILE.tag}
          glyph={OFF_TILE.glyph}
          accent={OFF_TILE.accent}
          // Explicit label so the button reads as "Off" and not "Off STANDBY ⏻".
          ariaLabel="Off"
          onClick={sleep}
        />
      </div>

      {/* One shared strip below the grid for whatever the last tap had to say:
        * AUX's instructions, or a failed sleep. Fixed height so the grid never
        * jumps around under the user's finger. */}
      <div style={{
        marginTop: 16,
        minHeight: 52,
        display: "flex",
        alignItems: "center",
      }}>
        {(infoCard || note) && (
          <div style={{
            padding: "12px 18px",
            background: theme.panel,
            border: `1px solid ${infoCard ? infoCard.accent : theme.rule}`,
            borderRadius: 12,
            fontSize: 16,
            lineHeight: 1.35,
            color: theme.ink,
            maxWidth: "100%",
          }}>{infoCard ? infoCard.blurb : note}</div>
        )}
      </div>

      {/* Whatever was playing before the user came back to Home stays one tap
        * away — tapping the title returns to the player rather than opening
        * lyrics (those live in the player). Renders nothing when idle. */}
      {showNowPlaying && <NowPlayingBar onOpen={onGoPlayer} />}
    </div>
  );
}

function Tile({ theme, name, tag, glyph, accent, ariaLabel, onClick }: {
  theme: SkinTheme;
  name: string;
  tag: string;
  glyph: string;
  accent: string;
  ariaLabel?: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={ariaLabel}
      style={{
        background: theme.panel,
        border: `2px solid ${theme.rule}`,
        borderTop: `6px solid ${accent}`,
        borderRadius: 16,
        color: theme.ink,
        cursor: "pointer",
        padding: "20px 22px",
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        justifyContent: "space-between",
        textAlign: "left",
        fontFamily: theme.font,
      }}
    >
      <span style={{
        width: 64, height: 64, borderRadius: 14,
        background: accent,
        color: "#000",
        display: "grid", placeItems: "center",
        fontSize: 30, fontWeight: 700,
        flexShrink: 0,
      }}>{glyph}</span>
      <span style={{width: "100%"}}>
        <span style={{
          display: "block",
          fontSize: 26, fontWeight: 800, letterSpacing: "-0.02em",
        }}>{name}</span>
        <span style={{
          display: "block",
          fontFamily: theme.mono,
          fontSize: 11,
          letterSpacing: "0.18em",
          color: theme.ink2,
          marginTop: 4,
        }}>{tag}</span>
      </span>
    </button>
  );
}
