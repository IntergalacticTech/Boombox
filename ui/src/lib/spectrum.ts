// Real-time audio visualizer hook backed by /audio/ws.
//
// The boombox-audio service taps the system's default sink monitor
// (whichever source is mixed onto the speakers) and broadcasts FFT bins +
// L/R RMS at ~21 fps. Skins consume this through useSpectrum() and treat
// the values as 0..1.
//
// Falls back to a smooth zero state when:
//   - the WS hasn't connected yet,
//   - audio is silent, or
//   - the service is down.
// In those cases the bins just stay at zero — skins can detect that via
// `live === false` and render their own decorative idle animation if
// they want.

import { useEffect, useRef, useState } from "react";

const N_BINS = 64;

export type SpectrumFrame = {
  bins: Float32Array;       // length N_BINS, 0..1
  peaks: Float32Array;      // length N_BINS, 0..1
  rmsL: number;             // 0..1
  rmsR: number;             // 0..1
  live: boolean;            // true when we received a frame in the last 2 s
  ts: number;               // ms since epoch of last frame
};

const ZERO: SpectrumFrame = {
  bins: new Float32Array(N_BINS),
  peaks: new Float32Array(N_BINS),
  rmsL: 0,
  rmsR: 0,
  live: false,
  ts: 0,
};

let _ws: WebSocket | null = null;
let _frame: SpectrumFrame = ZERO;
let _subs: Set<(f: SpectrumFrame) => void> = new Set();
let _lastFrameAt = 0;
let _liveTimer: ReturnType<typeof setInterval> | null = null;

function publish() {
  for (const sub of _subs) sub(_frame);
}

function ensureSocket() {
  if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${window.location.host}/audio/ws`;
  try {
    _ws = new WebSocket(url);
  } catch {
    setTimeout(ensureSocket, 1500);
    return;
  }
  _ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      const bins = msg.bins as number[] | undefined;
      const peaks = msg.peaks as number[] | undefined;
      const rms = msg.rms as [number, number] | undefined;
      if (!Array.isArray(bins) || bins.length !== N_BINS) return;
      const binArr = new Float32Array(N_BINS);
      const peakArr = new Float32Array(N_BINS);
      for (let i = 0; i < N_BINS; i++) {
        binArr[i] = bins[i] ?? 0;
        peakArr[i] = peaks?.[i] ?? bins[i] ?? 0;
      }
      _frame = {
        bins: binArr,
        peaks: peakArr,
        rmsL: rms?.[0] ?? 0,
        rmsR: rms?.[1] ?? 0,
        live: true,
        ts: Date.now(),
      };
      _lastFrameAt = _frame.ts;
      publish();
    } catch {
      // ignore malformed frames
    }
  };
  _ws.onclose = () => {
    _ws = null;
    setTimeout(ensureSocket, 1500);
  };
  _ws.onerror = () => {
    // onclose follows; we'll reconnect there.
  };
}

function startLivenessWatcher() {
  if (_liveTimer) return;
  _liveTimer = setInterval(() => {
    if (_frame.live && Date.now() - _lastFrameAt > 2000) {
      _frame = { ...ZERO, ts: _lastFrameAt };
      publish();
    }
  }, 1000);
}

/** Subscribe to spectrum frames. Returns the latest frame on each broadcast. */
export function useSpectrum(): SpectrumFrame {
  const [frame, setFrame] = useState<SpectrumFrame>(_frame);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    ensureSocket();
    startLivenessWatcher();
    const sub = (f: SpectrumFrame) => {
      if (mountedRef.current) setFrame(f);
    };
    _subs.add(sub);
    return () => {
      mountedRef.current = false;
      _subs.delete(sub);
    };
  }, []);

  return frame;
}
