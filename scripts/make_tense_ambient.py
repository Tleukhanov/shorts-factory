#!/usr/bin/env python3
"""Synthesize a slow, tense, cynical ambient loop for philosophical content.

Unlike the dark industrial loop (134 BPM, aggressive), this one is built for
long-form documentary narration: low drone, sparse tension, lots of space, and
no aggressive kicks.  Original synthesized material, no external samples.
"""

from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100
BPM = 68.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT


def _drone(n: int, sr: int) -> np.ndarray:
    """Slow low-frequency drone, two detuned sine waves with slow modulation."""
    t = np.arange(n) / sr
    # Deep sub-bass
    low = np.sin(2 * np.pi * 36.0 * t) * 0.35
    # Slightly detuned second harmonic for tension
    low2 = np.sin(2 * np.pi * 54.0 * t + 0.1) * 0.20
    # Slow amplitude modulation (breathing)
    mod = 0.5 + 0.5 * np.sin(2 * np.pi * 0.07 * t)
    return (low + low2) * mod


def _tension(n: int, sr: int) -> np.ndarray:
    """Sparse high-frequency tension: distant hum + occasional bell-like tones."""
    t = np.arange(n) / sr
    # Distant high hum
    hum = np.sin(2 * np.pi * 220.0 * t) * 0.04 * (0.3 + 0.7 * np.sin(2 * np.pi * 0.13 * t))
    # Occasional bell-like tones (every 8 beats)
    beat_len = int(BEAT * sr)
    bell = np.zeros(n)
    bell_freqs = [329.63, 392.00, 440.00, 493.88]  # E4, G4, A4, B4
    for i in range(0, n // (8 * beat_len)):
        start = i * 8 * beat_len
        freq = bell_freqs[i % len(bell_freqs)]
        dur = int(0.8 * sr)
        end = min(start + dur, n)
        tt = np.arange(end - start) / sr
        env = np.exp(-tt * 3.0)
        bell[start:end] += np.sin(2 * np.pi * freq * tt) * env * 0.08
    return hum + bell


def _heartbeat(n: int, sr: int) -> np.ndarray:
    """Very quiet heartbeat-like pulse every 4 beats."""
    beat_len = int(BEAT * sr)
    pulse = np.zeros(n)
    for i in range(0, n // (4 * beat_len)):
        start = i * 4 * beat_len
        dur = int(0.15 * sr)
        end = min(start + dur, n)
        tt = np.arange(end - start) / sr
        # Low thump
        pulse[start:end] += np.sin(2 * np.pi * 55.0 * tt) * np.exp(-tt * 15.0) * 0.15
    return pulse


def _noise_floor(n: int, sr: int) -> np.ndarray:
    """Very subtle noise floor for texture."""
    rng = np.random.default_rng(42)
    noise = rng.standard_normal(n).astype(np.float64) * 0.003
    # Low-pass: just keep the rumble
    from scipy.signal import butter, filtfilt

    b, a = butter(2, 200 / (sr / 2), btype="low")
    return filtfilt(b, a, noise)


def make_tense_ambient(duration: float = 90.0, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Generate a slow, tense, cynical ambient loop."""
    n = int(duration * sr)
    drone = _drone(n, sr)
    tension = _tension(n, sr)
    heartbeat = _heartbeat(n, sr)
    noise = _noise_floor(n, sr)

    mix = drone + tension + heartbeat + noise
    # Soft limit to avoid clipping
    mix = np.tanh(mix * 0.8) * 0.85
    return mix.astype(np.float32)


def write_wav(path: Path, samples: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        data = (samples * 32767).astype(np.int16)
        w.writeframes(data.tobytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a tense ambient loop.")
    parser.add_argument("--out", type=Path, default=Path("data/music/tense_ambient.wav"))
    parser.add_argument("--duration", type=float, default=90.0)
    args = parser.parse_args(argv)

    print(f"Rendering {args.duration}s tense ambient loop ...")
    samples = make_tense_ambient(duration=args.duration)
    write_wav(args.out, samples)
    print(f"Wrote {args.out} ({len(samples)} samples, ~{len(samples) / SAMPLE_RATE:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
