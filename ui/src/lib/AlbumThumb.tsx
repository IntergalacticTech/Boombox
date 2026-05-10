// Small album-art thumbnail with a colour-hash fallback while loading
// or when no art can be found.

import { useAlbumArt } from "./albumArt";

type Props = {
  artist?: string | null;
  album?: string | null;
  track?: string | null;
  size?: number;
  /** A short string used for the fallback gradient hue (e.g. track title). */
  seed?: string;
  radius?: number;
};

function hueOf(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return Math.abs(h) % 360;
}

export function AlbumThumb({ artist, album, track, size = 40, seed, radius = 6 }: Props) {
  const url = useAlbumArt(artist, album, track);
  const hue = hueOf(seed ?? album ?? track ?? artist ?? "");
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
