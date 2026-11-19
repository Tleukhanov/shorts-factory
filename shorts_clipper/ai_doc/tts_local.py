"""Local TTS wrapper: Kokoro for English, Silero for Russian."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _cache_name(text: str, voice: str) -> str:
    return hashlib.sha1(f"{voice}:{text}".encode()).hexdigest()[:20] + ".wav"


def synthesize(text: str, voice: str, out_dir: Path, language: str = "en") -> Path | None:
    """Synthesize *text* to a WAV in *out_dir*. Returns None when unavailable."""
    if not text.strip():
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / _cache_name(text, voice)
    if cache.is_file() and cache.stat().st_size > 1000:
        return cache

    try:
        import numpy as np
        import scipy.io.wavfile as wav
    except Exception as exc:
        log.warning("numpy/scipy missing: %s", exc)
        return None

    try:
        if language == "ru":
            import torch

            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_tts",
                language="ru",
                speaker="ru_v3",
                trust_repo=True,
            )
            sample_rate = 48000
            audio = model.apply_tts(text=text, speaker=voice, sample_rate=sample_rate)
        else:
            import torch
            from kokoro import KPipeline

            pipe = KPipeline(lang_code="a", device="cpu")
            sample_rate = 24000
            chunks = []
            for piece in pipe(text, voice=voice):
                chunks.append(piece.audio.numpy())
            audio = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)

        data = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        wav.write(str(cache), sample_rate, data)
        return cache
    except Exception as exc:
        log.warning("TTS failed (%s): %s", voice, exc)
        return None
