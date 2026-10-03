import { useEffect, useState } from "react";

/** Phones below this width get bottom tabs; wider windows get the sidebar +
 *  Now Playing panel layout. */
export const DESKTOP_MIN_PX = 900;

function isDesktop(): boolean {
  return window.innerWidth >= DESKTOP_MIN_PX;
}

export function useIsDesktop(): boolean {
  const [desktop, setDesktop] = useState(isDesktop);
  useEffect(() => {
    const onResize = () => setDesktop(isDesktop());
    window.addEventListener("resize", onResize);
    onResize();
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return desktop;
}
