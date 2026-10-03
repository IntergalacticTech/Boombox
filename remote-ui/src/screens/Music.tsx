import type { CSSProperties } from "react";
import type { Navigate } from "../lib/route";
import { HomeLibrary } from "./HomeLibrary";
import { Library } from "./Library";

const tab = (active: boolean): CSSProperties => ({
  padding: "8px 16px", borderRadius: 999, fontSize: 14, border: "1px solid var(--rule)",
  background: active ? "var(--ink)" : "transparent",
  color: active ? "var(--bg)" : "var(--ink2)", cursor: "pointer",
});

/** Music: the Navidrome Home Library (default) or this boombox's own Mopidy
 *  library. #/music/home/… and #/music/boombox. */
export function Music({ params, navigate }: { params: string[]; navigate: Navigate }) {
  const source = params[0] === "boombox" ? "boombox" : "home";
  return (
    <div>
      <div role="tablist" aria-label="Music source"
           style={{ display: "flex", gap: 8, padding: "16px 16px 0", flexWrap: "wrap" }}>
        <button type="button" role="tab" aria-selected={source === "home"}
                onClick={() => navigate("music", ["home"])} style={tab(source === "home")}>
          Home Library
        </button>
        <button type="button" role="tab" aria-selected={source === "boombox"}
                onClick={() => navigate("music", ["boombox"])} style={tab(source === "boombox")}>
          On this boombox
        </button>
      </div>
      {source === "home"
        ? <HomeLibrary params={params.slice(1)} navigate={navigate} />
        : <Library />}
    </div>
  );
}
