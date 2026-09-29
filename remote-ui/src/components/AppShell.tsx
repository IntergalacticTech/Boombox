import type { ReactNode } from "react";
import { useHashRoute, type Navigate, type Route } from "../lib/route";
import { useIsDesktop } from "../lib/useIsDesktop";
import { TabBar, tabForRoute } from "./TabBar";
import { Sidebar } from "./Sidebar";
import { NowPanel } from "./NowPanel";
import { MiniPlayer } from "./MiniPlayer";
import { SectionMessage } from "./SectionMessage";
import { NowPlaying } from "../screens/NowPlaying";
import { Music } from "../screens/Music";
import { Playlists } from "../screens/Playlists";
import { Search } from "../screens/Search";
import { Files } from "../screens/Files";
import { More } from "../screens/More";
import { Video } from "../screens/Video";

export interface SectionProps { params: string[]; navigate: Navigate; desktop: boolean }

/** Route → section. Tasks for Music, Video and Accounts replace their cases. */
export function renderSection(route: Route, p: SectionProps, onOpenSettings: () => void,
                              adminLocked: boolean): ReactNode {
  switch (route) {
    case "now": return <NowPlaying onOpenLibrary={() => p.navigate("music")} />;
    case "music": return <Music params={p.params} navigate={p.navigate} />;
    case "video": return <Video params={p.params} navigate={p.navigate} />;
    case "search": return <Search autoFocus={p.desktop} />;
    case "playlists": return <Playlists />;
    case "files": return <Files />;
    case "accounts":
      return <SectionMessage title="Accounts" message="Admin isn't available in this version yet." />;
    case "more":
      return <More navigate={p.navigate} onOpenSettings={onOpenSettings} adminLocked={adminLocked} />;
  }
}

/** Phone (< 900 px): section + mini-player + bottom tabs.
 *  Desktop (≥ 900 px): sidebar | section | Now Playing + queue panel. */
export function AppShell({ onOpenSettings }: { onOpenSettings: () => void }) {
  const desktop = useIsDesktop();
  const { route, params, navigate } = useHashRoute();
  const adminLocked = true;
  const content = renderSection(route, { params, navigate, desktop }, onOpenSettings, adminLocked);

  if (desktop) {
    return (
      <div data-layout="desktop" style={{
        display: "grid", gridTemplateColumns: "220px minmax(0, 1fr) 360px", height: "100%",
      }}>
        <Sidebar active={route} onNavigate={(r) => navigate(r)}
                 onOpenSettings={onOpenSettings} adminLocked={adminLocked} />
        <main style={{ overflowY: "auto", minWidth: 0 }}>
          <div style={{ maxWidth: 1200, margin: "0 auto" }}>{content}</div>
        </main>
        <NowPanel />
      </div>
    );
  }
  return (
    <div data-layout="phone">
      <main style={{ minWidth: 0 }}>{content}</main>
      {route !== "now" && <MiniPlayer onOpenNow={() => navigate("now")} />}
      <TabBar active={tabForRoute(route)} onChange={(t) => navigate(t)} />
    </div>
  );
}
