#!/usr/bin/env python3
"""Procedural eurobeat interlude bed for Midnight Youkai Radio.

Renders a short 172 BPM loop (kick / snare / hats / saw bass / pluck arp / pad)
to a fixed-format wav, loudness-matched to the station bed level. Used to keep
the stream alive while the next track is still being prepared and as a floor
under DJ talk.
"""

import math
import random
import struct
import subprocess
import wave
from pathlib import Path

import radio_config as cfg

BPM = 172
BARS = 8
LOOP_SECONDS = round(BARS * 4 * 60.0 / BPM, 3)
SR = cfg.SAMPLE_RATE
N = int(LOOP_SECONDS * SR)


def _saw(freq: float, dur: float, amp: float = 0.5, harmonics: int = 10):
    n = int(dur * SR)
    out = [0.0] * n
    for h in range(1, harmonics + 1):
        f = freq * h
        if f > SR / 2.2:
            break
        a = amp / h
        step = 2 * math.pi * f / SR
        for i in range(n):
            out[i] += a * math.sin(step * i)
    return out


def _noise(dur: float, amp: float, decay: float, hp: bool = True):
    n = int(dur * SR)
    out = [0.0] * n
    prev = 0.0
    for i in range(n):
        s = random.uniform(-1, 1)
        if hp:
            s, prev = s - prev, s
        out[i] = amp * s * math.exp(-decay * i / SR)
    return out


def _kick(dur: float = 0.32):
    n = int(dur * SR)
    out = [0.0] * n
    phase = 0.0
    for i in range(n):
        t = i / SR
        f = 150 * math.exp(-28 * t) + 48
        phase += 2 * math.pi * f / SR
        env = math.exp(-9 * t)
        out[i] = math.sin(phase) * env * 0.95 + random.uniform(-1, 1) * 0.25 * math.exp(-160 * t)
    return out


def _snare(dur: float = 0.22):
    n = int(dur * SR)
    out = _noise(dur, 0.34, 22)
    for i in range(n):
        t = i / SR
        out[i] += math.sin(2 * math.pi * 210 * t) * 0.22 * math.exp(-16 * t)
    return out


def _hat(dur: float = 0.06, amp: float = 0.13):
    return _noise(dur, amp, 90)


def _pad(freqs, dur: float, amp: float = 0.07):
    n = int(dur * SR)
    out = [0.0] * n
    for k, f in enumerate(freqs):
        det = 1 + (k - len(freqs) / 2) * 0.0025
        step = 2 * math.pi * f * det / SR
        for i in range(n):
            t = i / SR
            swell = math.sin(math.pi * min(1.0, t / 0.6)) * math.exp(-0.35 * t)
            out[i] += amp * math.sin(step * i + k) * swell
    return out


def _add(buf, samples, start_sec: float, gain: float = 1.0):
    off = int(start_sec * SR)
    for i, s in enumerate(samples):
        j = off + i
        if 0 <= j < len(buf):
            buf[j] += s * gain


def render() -> list:
    rnd = random
    buf = [0.0] * N
    beat = 60.0 / BPM
    bar = 4 * beat
    step = beat / 4  # sixteenth
    rnd.seed(169)

    kick = _kick()
    snare = _snare()
    hat = _hat()
    hat_open = _hat(0.14, 0.09)

    roots = [55.0, 55.0, 43.65, 49.0, 55.0, 55.0, 73.42, 65.41]  # A A F G A A D E
    bass_bank = {f: _saw(f, beat * 0.55, 0.5, 8) for f in set(roots)}

    scale = [440.0, 523.25, 659.25, 880.0, 659.25, 523.25, 587.33, 440.0]
    pluck_bank = {f: _saw(f, 0.16, 0.16, 14) for f in set(scale)}

    chords = []
    for root in (55.0, 43.65, 49.0, 65.41):
        chords.append(_pad([root * 4, root * 4 * 1.2, root * 4 * 1.5], bar, 0.06))

    for b in range(BARS):
        t0 = b * bar
        for k in range(4):
            _add(buf, kick, t0 + k * beat, 1.0)
            _add(buf, hat_open, t0 + k * beat + beat * 0.5, 0.55)
            if k in (1, 3):
                _add(buf, snare, t0 + k * beat, 0.9)
        for s16 in range(8):
            _add(buf, bass_bank[roots[b]], t0 + s16 * (beat / 2), 0.5)
        for s16 in range(16):
            if s16 % 2 == 1:
                _add(buf, hat, t0 + s16 * step, 0.5)
            if s16 % 4 == 2 or s16 % 8 == 5:
                _add(buf, pluck_bank[scale[(b * 3 + s16) % len(scale)]], t0 + s16 * step, 0.55)
        _add(buf, chords[b % len(chords)], t0, 0.75)

    peak = max(abs(v) for v in buf) or 1.0
    norm = 0.72 / peak
    return [max(-1.0, min(1.0, v * norm)) for v in buf]


def write_wav(path: Path, mono: list, gain_db: float = 0.0) -> None:
    g = 10 ** (gain_db / 20.0)
    fade = int(0.02 * SR)
    data = bytearray()
    for i, v in enumerate(mono):
        s = v * g
        if i < fade:
            s *= i / fade
        elif i > len(mono) - fade:
            s *= (len(mono) - i) / fade
        sample = int(max(-1.0, min(1.0, s)) * 32000)
        data += struct.pack("<hh", sample, sample)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(bytes(data))


def build(force: bool = False) -> Path:
    if cfg.BED_FILE.exists() and not force and cfg.BED_FILE.stat().st_size > 100000:
        return cfg.BED_FILE
    raw = cfg.BED_FILE.with_suffix(".raw.wav")
    shaped = cfg.BED_FILE.with_suffix(".shaped.wav")
    write_wav(raw, render())
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw),
         "-af", "lowpass=f=11000,aecho=0.8:0.75:70:0.22",
         "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(shaped)],
        check=False,
    )
    gain_db = 0.0
    try:
        import dj_engine
        gain_db = max(-12.0, min(12.0, dj_engine.gain_for_loudness(shaped, cfg.BED_LUFS)))
    except Exception:
        pass
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(shaped),
         "-af", f"volume={gain_db:.2f}dB,alimiter=limit=0.95:level=disabled",
         "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(cfg.BED_FILE)],
        check=False,
    )
    raw.unlink(missing_ok=True)
    shaped.unlink(missing_ok=True)
    return cfg.BED_FILE


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    p = build(force=True)
    print(f"bed -> {p} ({LOOP_SECONDS}s, {p.stat().st_size} bytes)")
