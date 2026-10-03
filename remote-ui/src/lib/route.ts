import { useCallback, useEffect, useState } from "react";

/** App sections, addressed by the URL hash (#/music/…) so browser back /
 *  forward and links work without a router dependency. `more` is the
 *  phone's More tab. */
export type Route =
  | "now" | "music" | "video" | "search" | "playlists" | "files" | "accounts" | "storage" | "more";

export const ROUTES: readonly Route[] = [
  "now", "music", "video", "search", "playlists", "files", "accounts", "storage", "more",
];

export interface HashLocation { route: Route; params: string[] }

export type Navigate = (route: Route, params?: string[]) => void;

function decode(part: string): string {
  try { return decodeURIComponent(part); } catch { return part; }
}

export function parseHash(hash: string): HashLocation {
  const parts = hash.replace(/^#\/?/, "").split("/").filter((p) => p !== "").map(decode);
  const head = parts[0] ?? "";
  if ((ROUTES as readonly string[]).includes(head)) {
    return { route: head as Route, params: parts.slice(1) };
  }
  return { route: "now", params: [] };
}

export function hashFor(route: Route, params: string[] = []): string {
  return "#/" + [route, ...params.map((p) => encodeURIComponent(p))].join("/");
}

export function useHashRoute(): HashLocation & { navigate: Navigate } {
  const [loc, setLoc] = useState<HashLocation>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setLoc(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    onChange();
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const navigate = useCallback<Navigate>((route, params = []) => {
    const next = hashFor(route, params);
    // Assigning the hash pushes a history entry and fires `hashchange`.
    if (window.location.hash !== next) window.location.hash = next;
  }, []);
  return { ...loc, navigate };
}
