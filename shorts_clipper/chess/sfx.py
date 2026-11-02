"""Short synthesized sound effects for the drama format.

No external assets and no new dependencies: each cue is a fraction of a second
of numpy-generated samples written as 48 kHz stereo 16-bit PCM.  A checkout
without a sound pack still renders the buzz, ding, whoosh and impact the edit
cuts on, and every cue is deterministic so two renders of the same plan sound
the same.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path

log = logging.getLogger(__name__)

SAMPLE_RATE = 48_000
CHANNELS = 2
# Every cue is normalized to this peak.  Below the 0.8 ceiling from the mix
# contract, high enough to survive the music bed without a per-cue gain stage.
PEAK = 0.75
WRONG_SECONDS = 0.35
DING_SECONDS = 0.45
WHOOSH_SECONDS = 0.25
IMPACT_SECONDS = 0.30
_SEED = 20_240_517


def _envelope(seconds, attack: float, decay: float):
    """Fast-attack, exponential-decay amplitude envelope."""
    import numpy as np

    rise = np.clip(seconds / max(attack, 1e-6), 0.0, 1.0)
    return rise * np.exp(-seconds / max(decay, 1e-6))


def _fade_out(seconds, duration: float, length: float = 0.02):
    """Linear tail fade so the file never ends on a click."""
    import numpy as np

    return np.clip((duration - seconds) / max(length, 1e-6), 0.0, 1.0)


def _write_wav(path: str | Path, samples) -> Path:
    """Write mono or stereo float samples as 48 kHz 16-bit stereo PCM."""
    import numpy as np

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(samples, dtype=np.float64)
    if data.ndim == 1:
        data = np.column_stack((data, data))
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    if peak > 0.0:
        data = data * (PEAK / peak)
    pcm = np.clip(data, -1.0, 1.0)
    frames = (pcm * 32767).astype(np.int16)
    with wave.open(str(out), "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(frames.tobytes())
    return out


def wrong_buzz(path: str | Path) -> Path:
    """A ~0.35s low saw/square buzz with a fast decay: the "wrong" UI sound."""
    import numpy as np

    n = int(SAMPLE_RATE * WRONG_SECONDS)
    seconds = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    # Falling pitch makes the buzz read as a rejection rather than a held tone.
    frequency = np.linspace(120.0, 80.0, n)
    phase = 2.0 * np.pi * np.cumsum(frequency) / SAMPLE_RATE
    saw = 2.0 * ((phase / (2.0 * np.pi)) % 1.0) - 1.0
    square = np.sign(np.sin(phase * 0.5))
    tone = 0.65 * saw + 0.35 * square
    samples = tone * _envelope(seconds, 0.004, 0.09) * _fade_out(
        seconds, WRONG_SECONDS
    )
    return _write_wav(path, samples)


def correct_ding(path: str | Path) -> Path:
    """A ~0.45s bright two-tone ding at 880 + 1320 Hz."""
    import numpy as np

    n = int(SAMPLE_RATE * DING_SECONDS)
    seconds = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    tone = 0.6 * np.sin(2.0 * np.pi * 880.0 * seconds)
    tone += 0.4 * np.sin(2.0 * np.pi * 1320.0 * seconds)
    # A quiet octave above the root keeps the ding bright on phone speakers.
    tone += 0.12 * np.sin(2.0 * np.pi * 1760.0 * seconds)
    samples = tone * _envelope(seconds, 0.002, 0.17) * _fade_out(
        seconds, DING_SECONDS
    )
    return _write_wav(path, samples)


def whoosh(path: str | Path) -> Path:
    """A ~0.25s band-passed noise sweep from high to low."""
    import numpy as np

    rng = np.random.default_rng(_SEED)
    n = int(SAMPLE_RATE * WHOOSH_SECONDS)
    seconds = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    noise = rng.standard_normal(n)

    # Chamberlin state-variable band-pass with a downward-swept centre.  The
    # filter is stable here because the largest coefficient stays below 1.
    sweep = np.geomspace(6000.0, 500.0, n)
    coefficient = 2.0 * np.sin(np.pi * sweep / SAMPLE_RATE)
    damp = 1.0
    low = 0.0
    band = 0.0
    shaped = np.empty(n, dtype=np.float64)
    for index in range(n):
        high = noise[index] - low - damp * band
        band += coefficient[index] * high
        low += coefficient[index] * band
        shaped[index] = band

    envelope = np.sin(np.pi * np.clip(seconds / WHOOSH_SECONDS, 0.0, 1.0)) ** 2
    return _write_wav(path, shaped * envelope)


def impact(path: str | Path) -> Path:
    """A ~0.3s low sine thump (90 -> 45 Hz) with a short click."""
    import numpy as np

    rng = np.random.default_rng(_SEED + 1)
    n = int(SAMPLE_RATE * IMPACT_SECONDS)
    seconds = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    frequency = np.linspace(90.0, 45.0, n)
    phase = 2.0 * np.pi * np.cumsum(frequency) / SAMPLE_RATE
    thump = np.sin(phase) * _envelope(seconds, 0.001, 0.09)

    click_n = max(1, int(SAMPLE_RATE * 0.012))
    click = np.zeros(n, dtype=np.float64)
    click[:click_n] = rng.standard_normal(click_n) * np.exp(
        -np.arange(click_n, dtype=np.float64) / (SAMPLE_RATE * 0.002)
    )
    samples = 0.85 * thump + 0.22 * click
    samples *= _fade_out(seconds, IMPACT_SECONDS)
    return _write_wav(path, samples)


def synthesize_sfx(out_dir: str | Path) -> dict[str, Path]:
    """Write every cue into *out_dir* and return ``{name: path}``."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "wrong_buzz": directory / "wrong_buzz.wav",
        "correct_ding": directory / "correct_ding.wav",
        "whoosh": directory / "whoosh.wav",
        "impact": directory / "impact.wav",
    }
    wrong_buzz(paths["wrong_buzz"])
    correct_ding(paths["correct_ding"])
    whoosh(paths["whoosh"])
    impact(paths["impact"])
    log.debug("synthesized SFX in %s", directory)
    return paths
