import { describe, it, expect, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { TransportProvider, useRemote } from "./store";
import type {
  Transport, RemoteState, ConnectionStatus,
} from "../transport/types";

function makeFakeTransport() {
  let stateCb: ((s: RemoteState) => void) | null = null;
  let statusCb: ((s: ConnectionStatus) => void) | null = null;
  const t: Transport = {
    kind: "http",
    connect: vi.fn().mockResolvedValue(undefined),
    disconnect: vi.fn(),
    onState: (cb) => { stateCb = cb; return () => {}; },
    onStatus: (cb) => { statusCb = cb; return () => {}; },
    command: vi.fn().mockResolvedValue({ ok: true }),
  };
  return {
    transport: t,
    pushState: (s: RemoteState) => stateCb?.(s),
    pushStatus: (s: ConnectionStatus) => statusCb?.(s),
  };
}

const sample: RemoteState = {
  boombox: { id: "b", name: "B", version: 1 },
  source: "mopidy", playing: true,
  track: { title: "Hey", artist: "X", album: "Y",
           duration_s: 10, position_s: 1 },
  art_hash: null, art_url: null, volume: 42, muted: false,
  sources_available: [], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: { bg: "#abc" },
};

function Probe() {
  const { state, status } = useRemote();
  return (
    <div>
      <span data-testid="title">{state?.track?.title ?? "—"}</span>
      <span data-testid="status">{status}</span>
    </div>
  );
}

describe("TransportProvider / useRemote", () => {
  it("connects the transport and exposes pushed state", async () => {
    const { transport, pushState } = makeFakeTransport();
    render(
      <TransportProvider transport={transport}>
        <Probe />
      </TransportProvider>,
    );
    expect(transport.connect).toHaveBeenCalled();
    expect(screen.getByTestId("title").textContent).toBe("—");
    await act(async () => { pushState(sample); });
    expect(screen.getByTestId("title").textContent).toBe("Hey");
  });

  it("applies the theme from each state push", async () => {
    const { transport, pushState } = makeFakeTransport();
    render(
      <TransportProvider transport={transport}>
        <Probe />
      </TransportProvider>,
    );
    await act(async () => { pushState(sample); });
    expect(document.documentElement.style.getPropertyValue("--bg"))
      .toBe("#abc");
  });

  it("exposes connection status changes", async () => {
    const { transport, pushStatus } = makeFakeTransport();
    render(
      <TransportProvider transport={transport}>
        <Probe />
      </TransportProvider>,
    );
    await act(async () => { pushStatus("disabled"); });
    expect(screen.getByTestId("status").textContent).toBe("disabled");
  });

  it("a rejected connect() does NOT overwrite a more-specific status already pushed", async () => {
    // Simulate: HttpTransport's onclose(4403) synchronously emits "disabled"
    // and THEN connect() rejects. Without the functional-setState guard, the
    // .catch overwrites "disabled" with "error".
    const { transport, pushStatus } = makeFakeTransport();
    (transport.connect as ReturnType<typeof vi.fn>)
      .mockImplementationOnce(() => {
        pushStatus("disabled");
        return Promise.reject(new Error("ws closed: 4403"));
      });
    render(
      <TransportProvider transport={transport}>
        <Probe />
      </TransportProvider>,
    );
    // Wait for the rejected promise's microtask to settle.
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId("status").textContent).toBe("disabled");
  });
});
