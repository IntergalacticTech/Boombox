// Small album-art thumbnail with a colour-hash fallback while loading
// or when no art can be found.
//
// Two source modes:
//   1. artId (preferred): /api/library/art/<id> — a LAN-local Navidrome
//      proxy with a server-side disk cache. Sub-millisecond on a warm
//      cache, works fully offline once a row has been seen.
//   2. artist/album/track (fallback): /api/art — iTunes Search. Used by
//      the legacy Mopidy-Local browse tree which has no Subsonic ids.
//
// If the artId fetch 404s (e.g. Navidrome offline and no cached bytes),
// we fall through to the gradient — chasing iTunes for a private library
// is futile.

import { useState } from "react";
import { useAlbumArt } from "./albumArt";

type Props = {
  artist?: string | null;
  album?: string | null;
  track?: string | null;
  size?: number;
  /** A short string used for the fallback gradient hue (e.g. track title). */
  seed?: string;
  radius?: number;
  /** Subsonic art id — when present we skip iTunes and use the local proxy. */
  artId?: string | null;
};

function hueOf(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return Math.abs(h) % 360;
}

export function AlbumThumb({ artist, album, track, size = 40, seed, radius = 6, artId }: Props) {
  const [localArtFailed, setLocalArtFailed] = useState(false);
  const useLocal = !!artId && !localArtFailed;
  // Only kick off the iTunes hook when we don't have (or have given up on) a local id.
  const itunesUrl = useAlbumArt(
    useLocal ? null : artist,
    useLocal ? null : album,
    useLocal ? null : track,
  );
  const hue = hueOf(seed ?? album ?? track ?? artist ?? "");
  // Request a 2x density bitmap for retina-class displays. Navidrome will
  // downscale server-side; iTunes URLs already encode a fixed size.
  const localUrl = useLocal
    ? `/api/library/art/${encodeURIComponent(artId!)}?size=${Math.min(600, size * 2)}`
    : null;
  const url = localUrl ?? itunesUrl;
  return (
    <div style={{
      width: size, height: size, borderRadius: radius,
      background: `linear-gradient(135deg, hsl(${hue}, 70%, 55%), hsl(${(hue + 60) % 360}, 60%, 35%))`,
      flexShrink: 0,
      overflow: "hidden",
      position: "relative",
    }}>
      {url && (
        <img
          src={url}
          alt=""
          loading="lazy"
          decoding="async"
          width={size}
          height={size}
          onError={() => { if (useLocal) setLocalArtFailed(true); }}
          style={{
            width: "100%", height: "100%",
            objectFit: "cover",
            display: "block",
          }}
        />
      )}
    </div>
  );
}
