"""Configuration for the AI documentary pipeline."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path


@dataclasses.dataclass
class AiDocumentaryConfig:
    """Defaults tuned for a long-form philosophical documentary."""

    language: str = "en"
    # Kokoro voice ids: af_heart (calm female), bm_george (documentary male).
    # Russian fallbacks via Silero: baya (female), aidar (male).
    voice_en: str = "bm_george"
    voice_ru: str = "baya"
    image_width: int = 1920
    image_height: int = 1080
    fps: int = 24
    crossfade: float = 0.8
    music_volume: float = 0.10
    voice_volume: float = 1.0
    burn_subtitles: bool = True
    # Painterly style suffix used when fetching or generating images.
    style_suffix: str = "old master oil painting, dark moody chiaroscuro, cinematic composition"
    music_path: str = "data/music/dark_industrial_loop.wav"

    @classmethod
    def from_file(cls, path: str | Path) -> AiDocumentaryConfig:
        path = Path(path)
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})

    def to_file(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(dataclasses.asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
