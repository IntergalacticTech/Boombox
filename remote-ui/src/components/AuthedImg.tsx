import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useApi } from "../lib/api";

/** An image from a pair-token-gated route. <img src> can't send the bearer
 *  token (and putting it in the URL would land it in nginx logs), so fetch
 *  the bytes and show an object URL. Loads once the tile is near the
 *  viewport; a placeholder panel otherwise or on failure. */
export function AuthedImg({ path, alt, style }: {
  path: string | null; alt: string; style?: CSSProperties;
}) {
  const api = useApi();
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === "undefined");
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    if (visible || !ref.current) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setVisible(true);
        io.disconnect();
      }
    }, { rootMargin: "300px" });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [visible]);

  useEffect(() => {
    if (!visible || !path || !api.getBlob) return;
    let url: string | null = null;
    let cancelled = false;
    api.getBlob(path).then((blob) => {
      if (cancelled) return;
      url = URL.createObjectURL(blob);
      setSrc(url);
    }).catch(() => { /* keep the placeholder */ });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
      setSrc(null);
    };
  }, [visible, path, api]);

  return (
    <div ref={ref} style={{ background: "var(--panel)", overflow: "hidden", ...style }}>
      {src && <img src={src} alt={alt}
                   style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />}
    </div>
  );
}
