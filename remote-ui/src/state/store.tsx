import {
  createContext, useContext, useEffect, useRef, useState,
} from "react";
import type { ReactNode } from "react";
import type {
  Transport, RemoteState, ConnectionStatus, CommandResult,
} from "../transport/types";
import { applyTheme } from "./theme";

interface RemoteContextValue {
  state: RemoteState | null;
  status: ConnectionStatus;
  command(action: string, value?: unknown): Promise<CommandResult>;
}

const RemoteContext = createContext<RemoteContextValue | null>(null);

/** Owns the transport: connects it, subscribes to state + status pushes,
 *  applies the device theme on every state push, and exposes everything to
 *  the tree via context. */
export function TransportProvider(
  { transport, children }: { transport: Transport; children: ReactNode },
) {
  const [state, setState] = useState<RemoteState | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const transportRef = useRef(transport);
  transportRef.current = transport;

  useEffect(() => {
    const t = transport;
    const offState = t.onState((s) => {
      setState(s);
      applyTheme(s.theme);
    });
    const offStatus = t.onStatus?.((s) => setStatus(s));
    // The transport itself emits "connected" via onStatus on successful
    // open; we only surface a hard-failure here. Functional setState
    // ensures we don't clobber a more-specific status (disabled /
    // unauthorized / unavailable) that the transport pushed synchronously
    // from onclose before connect()'s reject microtask fires.
    t.connect().catch(() =>
      setStatus((cur) => (cur === "connecting" ? "error" : cur)),
    );
    return () => {
      offState();
      offStatus?.();
      t.disconnect();
    };
  }, [transport]);

  const value: RemoteContextValue = {
    state,
    status,
    command: (action, v) => transportRef.current.command(action, v),
  };
  return (
    <RemoteContext.Provider value={value}>{children}</RemoteContext.Provider>
  );
}

/** Access the live remote state, connection status, and command sender. */
export function useRemote(): RemoteContextValue {
  const ctx = useContext(RemoteContext);
  if (!ctx) {
    throw new Error("useRemote must be used within a TransportProvider");
  }
  return ctx;
}
