import { describe, it, expect, vi } from "vitest";
import { BleTransport } from "./BleTransport";
import type { RemoteState } from "./types";

const sampleState: RemoteState = {
  boombox: { id: "b", name: "B", version: 1 },
  source: "airplay", playing: false, track: null,
  art_hash: null, art_url: null, volume: null, muted: true,
  sources_available: [], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: {},
};

// A fake GATT characteristic supporting notify + write.
function fakeChar() {
  let listener: ((e: Event) => void) | null = null;
  return {
    writes: [] as string[],
    startNotifications: vi.fn().mockResolvedValue(undefined),
    addEventListener: vi.fn((_t: string, cb: (e: Event) => void) => {
      listener = cb;
    }),
    writeValue: vi.fn(function (this: unknown, buf: BufferSource) {
      // record the decoded JSON the transport wrote
      const text = new TextDecoder().decode(buf as ArrayBuffer);
      (this as { writes: string[] }).writes.push(text);
      return Promise.resolve();
    }),
    // test helper: simulate a notify with the given object
    _notify(obj: unknown) {
      const json = JSON.stringify(obj);
      const buf = new TextEncoder().encode(json);
      const evt = { target: { value: new DataView(buf.buffer) } } as unknown as Event;
      listener?.(evt);
    },
  };
}

describe("BleTransport", () => {
  it("kind is 'ble'", () => {
    const state = fakeChar();
    const command = fakeChar();
    const t = new BleTransport(state as never, command as never);
    expect(t.kind).toBe("ble");
  });

  it("connect() subscribes to the state characteristic and pushes parsed state", async () => {
    const state = fakeChar();
    const command = fakeChar();
    const t = new BleTransport(state as never, command as never);
    const seen: RemoteState[] = [];
    t.onState((s) => seen.push(s));
    await t.connect();
    expect(state.startNotifications).toHaveBeenCalled();
    state._notify({ ok: true, data: sampleState });
    expect(seen).toHaveLength(1);
    expect(seen[0].source).toBe("airplay");
  });

  it("command() writes JSON to the command characteristic", async () => {
    const state = fakeChar();
    const command = fakeChar();
    const t = new BleTransport(state as never, command as never);
    await t.command("volume", 70);
    expect(command.writes).toHaveLength(1);
    expect(JSON.parse(command.writes[0])).toEqual({ action: "volume", value: 70 });
  });
});
