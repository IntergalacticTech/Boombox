"""Quadrature decoder for the rotary encoder."""
from __future__ import annotations

import boombox_buttons as bb


def test_cw_rotation_emits_one_step():
    """CW rotation transitions: 11 -> 01 -> 00 -> 10 -> 11 (one detent)."""
    dec = bb.EncoderDecoder()
    out = []
    for ab in [(0, 1), (0, 0), (1, 0), (1, 1)]:
        out.extend(dec.feed(a=ab[0], b=ab[1]))
    assert out == [("cw",)]


def test_ccw_rotation_emits_one_step():
    """CCW: 11 -> 10 -> 00 -> 01 -> 11."""
    dec = bb.EncoderDecoder()
    out = []
    for ab in [(1, 0), (0, 0), (0, 1), (1, 1)]:
        out.extend(dec.feed(a=ab[0], b=ab[1]))
    assert out == [("ccw",)]


def test_partial_rotation_does_not_emit():
    """Half a detent (11 -> 01 -> 11) emits nothing."""
    dec = bb.EncoderDecoder()
    out = []
    out.extend(dec.feed(a=0, b=1))
    out.extend(dec.feed(a=1, b=1))
    assert out == []


def test_noise_pulses_do_not_emit():
    """Bouncy noise: 11 -> 01 -> 11 -> 01 -> 11 emits nothing."""
    dec = bb.EncoderDecoder()
    out = []
    for ab in [(0, 1), (1, 1), (0, 1), (1, 1)]:
        out.extend(dec.feed(a=ab[0], b=ab[1]))
    assert out == []


def test_multiple_consecutive_detents():
    dec = bb.EncoderDecoder()
    out = []
    # Two CW detents back to back.
    for ab in [(0, 1), (0, 0), (1, 0), (1, 1), (0, 1), (0, 0), (1, 0), (1, 1)]:
        out.extend(dec.feed(a=ab[0], b=ab[1]))
    assert out == [("cw",), ("cw",)]
