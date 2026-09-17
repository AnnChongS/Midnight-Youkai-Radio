#!/usr/bin/env python3
"""Inaudible 16 kHz sync marker for Midnight Youkai Radio.

A three-pulse near-ultrasonic burst is mixed into every track (and injected on
demand for client calibration). Browsers can see it in an AnalyserNode, so the
player knows exactly when the audio it hears reached the track start - no more
guessing at the encoder / icecast / buffer latency.
"""

import math
import struct
import wave
from pathlib import Path

import radio_config as cfg

FREQ = float(cfg.MARKER_FREQ)
PULSE_MS = cfg.MARKER_PULSE_MS
GAP_MS = cfg.MARKER_GAP_MS
PULSES = cfg.MARKER_PULSES
PEAK = 10 ** (cfg.MARKER_LEVEL_DB / 20.0)


def _samples() -> list:
    out = []
    for p in range(PULSES):
        n = int(cfg.SAMPLE_RATE * PULSE_MS / 1000)
        ramp = int(cfg.SAMPLE_RATE * 0.004)
        for i in range(n):
            env = 1.0
            if i < ramp:
                env = i / ramp
            elif i > n - ramp:
                env = (n - i) / ramp
            out.append(math.sin(2 * math.pi * FREQ * i / cfg.SAMPLE_RATE) * PEAK * env)
        out.extend([0.0] * int(cfg.SAMPLE_RATE * GAP_MS / 1000))
    return out


def pcm() -> bytes:
    """28-byte-friendly interleaved s16le stereo PCM of the marker burst."""
    data = bytearray()
    for v in _samples():
        s = int(max(-1.0, min(1.0, v)) * 32767)
        data += struct.pack("<hh", s, s)
    return bytes(data)


def duration_ms() -> int:
    return PULSES * PULSE_MS + (PULSES - 1) * GAP_MS


def build(force: bool = False) -> Path:
    if cfg.MARKER_FILE.exists() and not force and cfg.MARKER_FILE.stat().st_size > 1000:
        return cfg.MARKER_FILE
    with wave.open(str(cfg.MARKER_FILE), "wb") as wf:
        wf.setnchannels(cfg.CHANNELS)
        wf.setsampwidth(cfg.SAMPLE_WIDTH)
        wf.setframerate(cfg.SAMPLE_RATE)
        wf.writeframes(pcm())
    return cfg.MARKER_FILE


if __name__ == "__main__":
    p = build(force=True)
    print(f"marker -> {p} ({duration_ms()} ms, {p.stat().st_size} bytes)")
